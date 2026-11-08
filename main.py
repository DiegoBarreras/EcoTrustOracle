"""
EcoTrust Oracle - FastAPI Central Orchestrator
B2B SaaS Physical Oracle bridging real-world industrial meters and the Solana Blockchain.

Sequential Pipeline:
1. Vision Agent (Gemini / Claude / DeepSeek) -> Extracts meter reading into validated JSON (3-read consensus).
2. Web3 Oracle (Solana Devnet)              -> Hashes payload (SHA-256) & anchors via Memo program.
3. Notifier (Telegram Bot API)              -> Delivers ESG certificate to stakeholders.
"""

import math
import time
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.schemas import (
    MeterReading,
    AuditResponse,
    HealthResponse,
    NotificationResult,
    VerifyRequest,
    VerifyResult,
    VisionAnalysis,
    ESGCompliance,
    evaluate_compliance,
)
from core.vision_agent import analyze_meter_image, VisionExtractionError
from core.web3_oracle import anchor_reading_to_solana, verify_anchor, SolanaOracleError
from core.notifier import send_audit_notification, NotificationError, poll_telegram_commands

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
        "Extracts readings with a vision model (3 independent reads + majority vote), generates deterministic "
        "SHA-256 hashes, anchors on-chain via the native Solana Memo Program, and delivers Telegram ESG certificates."
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


def _check_counter(value: float, previous_value: Optional[float]) -> Optional[float]:
    """
    Meters are cumulative counters: consumption = current - previous reading.
    A reading below the previous one is a misread or tampering, so it is refused before anchoring.
    """
    if previous_value is None:
        return None
    if not math.isfinite(previous_value):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="previous_value must be a finite number")
    if value < previous_value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "reading_below_previous",
                "message": (
                    f"La lectura {value} es menor que la anterior {previous_value}. "
                    "Un medidor acumulativo no retrocede: posible error de lectura o manipulacion. No se anclo en Solana."
                ),
                "previous_value": previous_value,
                "value": value,
            },
        )
    return round(value - previous_value, 4)


async def _anchor_and_notify(
    reading: MeterReading,
    start_time: float,
    telegram_chat_id: Optional[str],
    vision: Optional[VisionAnalysis] = None,
    consumption: Optional[float] = None,
    force_simulated: bool = False,
    compliance: Optional[ESGCompliance] = None,
) -> AuditResponse:
    """Shared tail of every audit: anchor on Solana, notify Telegram, build the response."""
    try:
        logger.info(f"[Pipeline] Anchoring reading on Solana Devnet: {reading.value} {reading.unit}")
        oracle_proof = await anchor_reading_to_solana(reading, force_simulated=force_simulated, compliance=compliance)
    except SolanaOracleError as err:
        logger.error(f"Web3 Oracle failed: {err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Solana Devnet anchoring error: {err}",
        )

    audit_status = "success"
    try:
        logger.info("[Pipeline] Sending ESG audit notification to Telegram...")
        notification = await send_audit_notification(
            reading=reading,
            solscan_url=oracle_proof.solscan_url,
            data_hash=oracle_proof.data_hash,
            chat_id=telegram_chat_id,
            is_simulated=oracle_proof.is_simulated,
            consumption=consumption,
            compliance=compliance,
        )
    except NotificationError as err:
        # Partial success: the proof exists even though the alert was not delivered.
        logger.warning(f"Notification error: {err}")
        audit_status = "partial_success"
        notification = NotificationResult(
            sent=False,
            channel="telegram",
            recipient=telegram_chat_id or settings.TELEGRAM_CHAT_ID,
            message_id=None,
            is_mock=False,
            error=str(err),
        )

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
        compliance=compliance,
    )


@app.post(
    "/api/v1/audit-meter",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Oracle Audit"],
    summary="Full Physical-to-Blockchain Audit Pipeline",
    description=(
        "Uploads a meter photograph, extracts the reading with a vision model (3 independent reads + majority vote), "
        "computes a deterministic SHA-256 hash, anchors proof on Solana Devnet via the Memo program, "
        "and dispatches an ESG compliance certificate to Telegram. "
        "If previous_value is sent and the new reading is lower, nothing is anchored (409)."
    ),
)
async def audit_meter(
    file: UploadFile = File(..., description="Photograph of the industrial meter (jpeg, png, webp, heic; max 10 MB)"),
    meter_hint: Optional[str] = Form(None, max_length=500, description="Optional context (e.g. 'Main boiler gas flowmeter')"),
    device_id: Optional[str] = Form(None, max_length=128, description="Meter / asset tag (e.g. 'BOILER-03')"),
    previous_value: Optional[float] = Form(None, description="Previous counter reading of this meter, to compute consumption"),
    monthly_threshold: Optional[float] = Form(None, description="Expected monthly consumption threshold to evaluate against consumption"),
    telegram_chat_id: Optional[str] = Form(None, description="Optional Telegram chat ID override for alerts"),
):
    start_time = time.perf_counter()

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type '{content_type}'. Upload a JPEG, PNG, WEBP or HEIC photo.",
        )

    image_bytes = await file.read(MAX_IMAGE_BYTES + 1)
    if len(image_bytes) == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty (0 bytes).")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image is larger than {MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
        )

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

    if device_id and device_id.strip():
        reading.device_id = device_id.strip()
    consumption = _check_counter(reading.value, previous_value)
    thresh = monthly_threshold if monthly_threshold is not None else settings.ESG_MONTHLY_THRESHOLD
    compliance = evaluate_compliance(consumption, thresh, reading.unit)

    # A synthetic reading (no vision key configured) is never written to the chain.
    return await _anchor_and_notify(
        reading, start_time, telegram_chat_id, vision=vision, consumption=consumption,
        force_simulated=vision.is_mock, compliance=compliance
    )


@app.post(
    "/api/v1/audit-sensor",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Oracle Audit"],
    summary="Direct IoT Sensor Telemetry Ingestion",
    description=(
        "Receives meter measurements directly from connected hardware sensors "
        "(Modbus, Arduino, Raspberry Pi, SCADA, USB/Serial), hashes the canonical reading, "
        "and anchors proof directly to Solana Devnet without requiring camera image processing. "
        "If previous_value is sent and the new reading is lower, nothing is anchored (409)."
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
    logger.info(
        f"[Sensor Ingest] Received telemetry from device '{reading.device_id or 'anonymous'}': "
        f"{reading.value} {reading.unit} (source: {reading.source})"
    )

    # Automatically set source to iot_sensor if left as default ai_vision
    if reading.source == "ai_vision":
        reading.source = "iot_sensor"

    consumption = _check_counter(reading.value, previous_value)
    thresh = monthly_threshold if monthly_threshold is not None else settings.ESG_MONTHLY_THRESHOLD
    compliance = evaluate_compliance(consumption, thresh, reading.unit)
    return await _anchor_and_notify(
        reading, start_time, telegram_chat_id, consumption=consumption, compliance=compliance
    )


@app.post(
    "/api/v1/audit-meter-mock",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Oracle Audit"],
    summary="Mock Pipeline Execution (No Image Required)",
    description="Frontend/integration testing with synthetic data. Always simulated: never written to Solana.",
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

    return await _anchor_and_notify(custom_reading, start_time, telegram_chat_id, force_simulated=True)


@app.post(
    "/api/v1/verify",
    response_model=VerifyResult,
    tags=["Oracle Audit"],
    summary="Independently verify an anchored reading",
    description=(
        "Recomputes the SHA-256 of the submitted reading, fetches the Solana transaction, and checks that the "
        "EcoTrust memo holds that exact hash and was signed by this oracle's wallet."
    ),
)
async def verify(request: VerifyRequest):
    return await verify_anchor(request.reading, request.tx_signature)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
