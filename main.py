"""
EcoTrust Oracle - FastAPI Central Orchestrator
B2B SaaS Physical Oracle bridging real-world industrial meters and the Solana Blockchain.

Sequential Pipeline:
1. Vision Agent (Gemini / Claude / DeepSeek) -> Extracts meter reading into validated JSON (3-read consensus).
2. Comparison                               -> Against the device's previous reading (history or client value);
                                               suspicious readings are flagged, never dropped.
3. Web3 Oracle (Solana Devnet)              -> Hashes payload (SHA-256) & anchors via Memo program.
4. History + limits (SQLite)                -> Stores the audit and evaluates the device's consumption limit.
5. Notifier (Telegram Bot API)              -> Delivers ESG certificate and alerts to stakeholders.

Bill check: AI reads utility bills (per-field consensus), code compares them with the previous bill, the meter
photo or the device's last stored reading, and the result is anchored on Solana.
"""

import math
import time
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core import analytics, store
from core.bill_agent import BillExtractionError, canonical_bill_json, check_bill, explain_bill_check, extract_bill
from core.config import get_settings
from core.schemas import (
    MeterReading,
    AuditResponse,
    BillCheckResult,
    ConsumptionLimit,
    DeviceHistory,
    DeviceSummary,
    HealthResponse,
    LimitStatus,
    NotificationResult,
    PreviousReading,
    ReadingComparison,
    VerifyPayloadRequest,
    VerifyRequest,
    VerifyResult,
    VisionAnalysis,
    evaluate_compliance,
)
from core.vision_agent import analyze_meter_image, VisionExtractionError
from core.web3_oracle import anchor_payload, anchor_reading_to_solana, verify_anchor, verify_payload, SolanaOracleError
from core.notifier import (
    NotificationError,
    poll_telegram_commands,
    send_audit_notification,
    send_bill_check_notification,
)

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("ecotrust.orchestrator")

# Formats every supported vision provider accepts; SVG and other "image/*" types are rejected.
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/heic", "image/heif"}
# Inline image data is capped by the providers (~20 MB after base64) and sent 3 times for consensus.
MAX_IMAGE_BYTES = 10 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    settings = get_settings()
    logger.info("==================================================")
    logger.info(f"Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"Solana RPC: {settings.SOLANA_RPC_URL}")
    logger.info(f"Vision model: {'Configured' if settings.VISION_API_KEY else 'MOCK Fallback'}")
    logger.info(f"Telegram Bot: {'Configured' if settings.TELEGRAM_BOT_TOKEN else 'MOCK Fallback'}")
    logger.info(f"Audit history DB: {settings.DB_PATH}")
    logger.info("==================================================")

    stop_event = asyncio.Event()
    poller_task = None
    if settings.TELEGRAM_BOT_TOKEN:
        poller_task = asyncio.create_task(poll_telegram_commands(stop_event))

    yield

    logger.info("Shutting down EcoTrust Oracle Orchestrator...")
    if poller_task:
        stop_event.set()
        poller_task.cancel()
        try:
            await poller_task
        except asyncio.CancelledError:
            pass


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Physical Oracle bridging physical industrial meters and Solana Devnet. "
        "Extracts readings with a vision model (3 independent reads + majority vote), compares them with the "
        "device history, generates deterministic SHA-256 hashes, anchors on-chain via the native Solana Memo Program, "
        "checks utility bills with AI, and delivers Telegram ESG certificates and alerts."
    ),
    lifespan=lifespan,
)

# CORS configuration for cross-origin Hackathon frontends (e.g. Next.js, Vite/React)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    # The default handler echoes the rejected input; NaN/Infinity cannot be JSON-encoded and turned a 422 into a 500.
    errors = [{k: v for k, v in err.items() if k not in ("input", "ctx")} for err in exc.errors()]
    return JSONResponse(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, content={"detail": jsonable_encoder(errors)})


@app.get("/", tags=["System"])
async def root():
    """Service metadata and documentation pointers."""
    return {
        "service": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "operational",
        "docs_url": "/docs",
        "health_url": "/health",
        "audit_endpoint": "/api/v1/audit-meter",
        "bill_check_endpoint": "/api/v1/bill-check",
        "devices_endpoint": "/api/v1/devices",
        "verify_endpoint": "/api/v1/verify",
    }


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Reports which integrations are REALLY configured (mock fallbacks do not count as ready):
    - vision API key present
    - oracle wallet configured (SOLANA_PRIVATE_KEY or oracle-devnet.json)
    - Telegram bot token and chat IDs present
    """
    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        gemini_ready=bool(settings.VISION_API_KEY),
        solana_ready=bool(settings.SOLANA_PRIVATE_KEY) or Path("oracle-devnet.json").exists(),
        telegram_ready=bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID),
        network="solana-devnet",
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _read_image(upload: UploadFile, label: str = "file") -> Tuple[bytes, str]:
    """Validates type and size of an uploaded photo and returns (bytes, mime type)."""
    content_type = (upload.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{content_type}' for '{label}'. Upload a JPEG, PNG, WEBP or HEIC photo.",
        )
    data = await upload.read(MAX_IMAGE_BYTES + 1)
    if len(data) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Uploaded '{label}' is empty (0 bytes).")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"'{label}' is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )
    return data, content_type


def _clean_device_id(device_id: Optional[str]) -> Optional[str]:
    return device_id.strip() if device_id and device_id.strip() else None


async def _compare_with_previous(reading: MeterReading, previous_value: Optional[float]) -> Optional[ReadingComparison]:
    """
    Compares with the previous reading: the client's previous_value when sent, otherwise the device's last stored
    reading. Suspicious readings (counter going backwards, unit change, abnormal jump) are flagged, not refused.
    """
    history = await asyncio.to_thread(store.history, reading.device_id) if reading.device_id else []
    if previous_value is not None:
        if not math.isfinite(previous_value):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="previous_value must be a finite number")
        # The client only knows the value, not when it was taken, so elapsed time stays unknown.
        previous = PreviousReading(value=previous_value, unit=reading.unit, timestamp="", origin="client")
    elif history:
        last = history[-1]
        previous = PreviousReading(
            value=last.value,
            unit=last.unit,
            timestamp=last.timestamp,
            tx_signature=last.tx_signature,
            is_simulated=last.is_simulated,
            origin="history",
        )
    else:
        return None
    comparison = analytics.compare(reading, previous, history)
    if comparison.anomaly:
        logger.warning(f"[Pipeline] Anomaly on device '{reading.device_id}': {comparison.anomaly}")
    return comparison


async def _limit_status(device_id: Optional[str]) -> Optional[LimitStatus]:
    if not device_id:
        return None
    limit = await asyncio.to_thread(store.get_limit, device_id)
    if limit is None:
        return None
    entries = await asyncio.to_thread(store.history, device_id)
    return analytics.evaluate_limit(limit, entries, datetime.now(timezone.utc))


def _failed_notification(err: Exception, chat_id: Optional[str]) -> NotificationResult:
    return NotificationResult(
        sent=False,
        channel="telegram",
        recipient=chat_id or settings.TELEGRAM_CHAT_ID,
        message_id=None,
        is_mock=False,
        error=str(err),
    )


async def _run_audit(
    reading: MeterReading,
    start_time: float,
    telegram_chat_id: Optional[str],
    previous_value: Optional[float] = None,
    vision: Optional[VisionAnalysis] = None,
    monthly_threshold: Optional[float] = None,
    synthetic: bool = False,
) -> AuditResponse:
    """
    Shared tail of every audit: compare -> anchor -> store -> limit -> notify.
    Synthetic readings (mock vision, mock endpoint) are never written to Solana nor to the history.
    """
    comparison = None if synthetic and previous_value is None else await _compare_with_previous(reading, previous_value)
    consumption = comparison.consumption if comparison else None
    threshold = monthly_threshold if monthly_threshold is not None else settings.ESG_MONTHLY_THRESHOLD
    # A counter that went backwards has no meaningful consumption to judge against the threshold.
    compliance = evaluate_compliance(consumption, threshold, reading.unit) if consumption is None or consumption >= 0 else None

    try:
        logger.info(f"[Pipeline] Anchoring reading on Solana Devnet: {reading.value} {reading.unit}")
        oracle_proof = await anchor_reading_to_solana(reading, force_simulated=synthetic, compliance=compliance)
    except SolanaOracleError as err:
        logger.error(f"Web3 Oracle failed: {err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Solana Devnet anchoring error: {err}",
        )

    limit_status = None
    if reading.device_id and not synthetic:
        await asyncio.to_thread(store.save_reading, reading, oracle_proof, comparison)
        limit_status = await _limit_status(reading.device_id)

    audit_status = "success"
    try:
        logger.info("[Pipeline] Sending ESG audit notification to Telegram...")
        notification = await send_audit_notification(
            reading=reading,
            solscan_url=oracle_proof.solscan_url,
            data_hash=oracle_proof.data_hash,
            chat_id=telegram_chat_id,
            is_simulated=oracle_proof.is_simulated,
            comparison=comparison,
            limit_status=limit_status,
            consumption=consumption,
            compliance=compliance,
        )
    except NotificationError as err:
        # Partial success: the proof exists even though the alert was not delivered.
        logger.warning(f"Notification error: {err}")
        audit_status = "partial_success"
        notification = _failed_notification(err, telegram_chat_id)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info(f"[Pipeline Complete] {audit_status} in {elapsed_ms}ms")
    return AuditResponse(
        status=audit_status,
        reading=reading,
        oracle_proof=oracle_proof,
        notification=notification,
        execution_time_ms=elapsed_ms,
        vision=vision,
        consumption=consumption,
        comparison=comparison,
        limit_status=limit_status,
        compliance=compliance,
    )


# ---------------------------------------------------------------------------
# Audits
# ---------------------------------------------------------------------------

@app.post(
    "/api/v1/audit-meter",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Oracle Audit"],
    summary="Full Physical-to-Blockchain Audit Pipeline",
    description=(
        "Uploads a meter photograph, extracts the reading with a vision model (3 independent reads + majority vote), "
        "compares it with the device's previous reading, anchors the SHA-256 on Solana Devnet via the Memo program, "
        "stores it in the device history and dispatches an ESG certificate to Telegram. Readings that look altered "
        "(lower than the previous one, unit change, abnormal jump) are still anchored, flagged and alerted."
    ),
)
async def audit_meter(
    file: UploadFile = File(..., description="Photograph of the industrial meter (jpeg, png, webp, heic; max 10 MB)"),
    meter_hint: Optional[str] = Form(None, max_length=500, description="Optional context (e.g. 'Main boiler gas flowmeter')"),
    device_id: Optional[str] = Form(None, max_length=128, description="Meter / asset tag; enables history, comparison and limits"),
    previous_value: Optional[float] = Form(None, description="Override: previous counter reading (otherwise taken from history)"),
    monthly_threshold: Optional[float] = Form(None, description="Expected monthly consumption threshold (defaults to ESG_MONTHLY_THRESHOLD)"),
    telegram_chat_id: Optional[str] = Form(None, description="Optional Telegram chat ID override for alerts"),
):
    start_time = time.perf_counter()
    image_bytes, content_type = await _read_image(file)

    try:
        logger.info(f"[Pipeline] Processing meter image '{file.filename}' ({len(image_bytes)} bytes)")
        reading, vision = await analyze_meter_image(
            image_bytes=image_bytes,
            mime_type=content_type,
            meter_hint=meter_hint,
        )
    except VisionExtractionError as err:
        logger.error(f"Vision Agent failed: {err}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"AI Vision extraction error: {err}",
        )

    reading.device_id = _clean_device_id(device_id)
    return await _run_audit(
        reading,
        start_time,
        telegram_chat_id,
        previous_value=previous_value,
        vision=vision,
        monthly_threshold=monthly_threshold,
        synthetic=vision.is_mock,
    )


@app.post(
    "/api/v1/audit-sensor",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Oracle Audit"],
    summary="Direct IoT Sensor Telemetry Ingestion",
    description=(
        "Receives meter measurements directly from connected hardware sensors "
        "(Modbus, Arduino, Raspberry Pi, SCADA, USB/Serial), compares them with the device history, "
        "anchors the canonical reading on Solana Devnet and stores it, without camera image processing."
    ),
)
async def audit_sensor(
    reading: MeterReading,
    previous_value: Optional[float] = None,
    monthly_threshold: Optional[float] = None,
    telegram_chat_id: Optional[str] = None,
):
    """
    Ingests telemetry directly from connected IoT devices/sensors, bypassing computer vision.
    Demonstrates true modularity: any data source can be anchored to Solana.
    """
    start_time = time.perf_counter()
    reading.device_id = _clean_device_id(reading.device_id)
    logger.info(
        f"[Sensor Ingest] Received telemetry from device '{reading.device_id or 'anonymous'}': "
        f"{reading.value} {reading.unit} (source: {reading.source})"
    )

    # Automatically set source to iot_sensor if left as default ai_vision
    if reading.source == "ai_vision":
        reading.source = "iot_sensor"

    return await _run_audit(
        reading, start_time, telegram_chat_id, previous_value=previous_value, monthly_threshold=monthly_threshold
    )


@app.post(
    "/api/v1/audit-meter-mock",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Oracle Audit"],
    summary="Mock Pipeline Execution (No Image Required)",
    description="Frontend/integration testing with synthetic data. Always simulated: never written to Solana or history.",
)
async def audit_meter_mock(
    custom_reading: Optional[MeterReading] = None,
    telegram_chat_id: Optional[str] = None,
):
    """Quick testing harness that simulates a reading without needing a physical camera photo."""
    start_time = time.perf_counter()

    if custom_reading is None:
        custom_reading = MeterReading(
            value=235.60,
            unit="kWh",
            confidence=0.99,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

    return await _run_audit(custom_reading, start_time, telegram_chat_id, synthetic=True)


# ---------------------------------------------------------------------------
# Devices: history and consumption limits
# ---------------------------------------------------------------------------

@app.get("/api/v1/devices", response_model=List[DeviceSummary], tags=["History"], summary="Audited devices")
async def list_devices():
    return await asyncio.to_thread(store.devices)


async def _device_history(device_id: str, limit: int = 200) -> DeviceHistory:
    entries = await asyncio.to_thread(store.history, device_id, limit)
    consumption_limit = await asyncio.to_thread(store.get_limit, device_id)
    limit_status = (
        analytics.evaluate_limit(consumption_limit, await asyncio.to_thread(store.history, device_id), datetime.now(timezone.utc))
        if consumption_limit
        else None
    )
    return DeviceHistory(device_id=device_id, entries=entries, limit=consumption_limit, limit_status=limit_status)


@app.get(
    "/api/v1/devices/{device_id}/history",
    response_model=DeviceHistory,
    tags=["History"],
    summary="Readings of a device (oldest first) with its consumption limit status",
)
async def device_history(device_id: str, limit: int = Query(200, ge=1, le=1000)):
    return await _device_history(device_id, limit)


@app.put(
    "/api/v1/devices/{device_id}/limit",
    response_model=DeviceHistory,
    tags=["History"],
    summary="Set the consumption limit of a device (warning at 80 %, alert at 100 %)",
)
async def set_device_limit(device_id: str, limit: ConsumptionLimit):
    await asyncio.to_thread(store.set_limit, device_id, limit)
    return await _device_history(device_id)


@app.delete(
    "/api/v1/devices/{device_id}/limit",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["History"],
    summary="Remove the consumption limit of a device",
)
async def delete_device_limit(device_id: str):
    if not await asyncio.to_thread(store.delete_limit, device_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Device '{device_id}' has no limit")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Bill check
# ---------------------------------------------------------------------------

@app.post(
    "/api/v1/bill-check",
    response_model=BillCheckResult,
    status_code=status.HTTP_201_CREATED,
    tags=["Bill Check"],
    summary="AI utility-bill check against the previous bill and/or the meter",
    description=(
        "The vision model reads the bill (and optionally the previous bill and a meter photo) with per-field consensus. "
        "Code, not the model, runs every check (consumption arithmetic, estimated reading, bill vs meter, continuity, "
        "price change) and estimates any overcharge. Without a meter photo, the device's last stored reading is used. "
        "The checks are anchored on Solana and summarized to Telegram."
    ),
)
async def bill_check(
    bill: UploadFile = File(..., description="Photo of the current utility bill"),
    previous_bill: Optional[UploadFile] = File(None, description="Photo of the previous bill (optional)"),
    meter: Optional[UploadFile] = File(None, description="Photo of the meter (optional)"),
    device_id: Optional[str] = Form(None, max_length=128, description="Meter tag: uses its last stored reading when no meter photo is sent"),
    telegram_chat_id: Optional[str] = Form(None, description="Optional Telegram chat ID override"),
):
    bill_bytes, bill_type = await _read_image(bill, "bill")
    previous_img = await _read_image(previous_bill, "previous_bill") if previous_bill else None
    meter_img = await _read_image(meter, "meter") if meter else None
    device_id = _clean_device_id(device_id)

    try:
        bill_x, previous_x, meter_result = await asyncio.gather(
            extract_bill(bill_bytes, bill_type),
            extract_bill(*previous_img) if previous_img else asyncio.sleep(0),
            analyze_meter_image(meter_img[0], meter_img[1]) if meter_img else asyncio.sleep(0),
        )
    except (BillExtractionError, VisionExtractionError) as err:
        logger.error(f"Bill check extraction failed: {err}")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"AI extraction error: {err}")

    meter_reading, meter_vision = meter_result if meter_img else (None, None)
    if meter_reading is not None:
        meter_reading.device_id = device_id
    elif device_id:
        last = await asyncio.to_thread(store.last_reading, device_id)
        if last is not None:
            meter_reading = MeterReading(
                value=last.value,
                unit=last.unit,
                confidence=last.confidence,
                timestamp=last.timestamp,
                source=last.source,
                device_id=device_id,
            )

    checks, verdict, overcharge, currency = check_bill(bill_x, previous_x, meter_reading)
    canonical = canonical_bill_json({
        "bill": bill_x,
        "previous_bill": previous_x,
        "meter_reading": meter_reading,
        "checks": checks,
        "verdict": verdict,
        "overcharge_estimate": overcharge,
        "currency": currency,
    })
    synthetic = bill_x.is_mock or bool(previous_x and previous_x.is_mock) or bool(meter_vision and meter_vision.is_mock)

    try:
        oracle_proof, explanation = await asyncio.gather(
            anchor_payload(canonical, force_simulated=synthetic),
            explain_bill_check(checks, verdict, overcharge, currency, bill_x, previous_x, meter_reading),
        )
    except SolanaOracleError as err:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Solana Devnet anchoring error: {err}")

    result = BillCheckResult(
        bill=bill_x,
        previous_bill=previous_x,
        meter_reading=meter_reading,
        meter_vision=meter_vision,
        checks=checks,
        verdict=verdict,
        overcharge_estimate=overcharge,
        currency=currency,
        explanation=explanation,
        canonical_json=canonical,
        oracle_proof=oracle_proof,
    )
    try:
        result.notification = await send_bill_check_notification(result, chat_id=telegram_chat_id)
    except NotificationError as err:
        logger.warning(f"Bill check notification error: {err}")
        result.notification = _failed_notification(err, telegram_chat_id)
    return result


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------

@app.post(
    "/api/v1/verify",
    response_model=VerifyResult,
    tags=["Verification"],
    summary="Independently verify an anchored reading",
    description=(
        "Recomputes the SHA-256 of the submitted reading, fetches the Solana transaction, and checks that the "
        "EcoTrust memo holds that exact hash and was signed by this oracle's wallet."
    ),
)
async def verify(request: VerifyRequest):
    return await verify_anchor(request.reading, request.tx_signature)


@app.post(
    "/api/v1/verify-payload",
    response_model=VerifyResult,
    tags=["Verification"],
    summary="Independently verify any anchored canonical JSON (e.g. a bill check)",
)
async def verify_payload_endpoint(request: VerifyPayloadRequest):
    return await verify_payload(request.canonical_json, request.tx_signature)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
