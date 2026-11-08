"""
EcoTrust Oracle - FastAPI Central Orchestrator
B2B SaaS Physical Oracle bridging real-world industrial meters and the Solana Blockchain.

Sequential Pipeline:
1. Vision Agent (Gemini 1.5 Flash) -> Extracts meter reading into validated JSON.
2. Web3 Oracle (Solana Devnet)     -> Hashes payload (SHA-256) & anchors via Memo program.
3. Notifier (Telegram Bot API)     -> Delivers immutable ESG certificate to stakeholders.
"""

import time
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from core.config import get_settings
from core.schemas import (
    MeterReading,
    AuditResponse,
    HealthResponse,
)
from core.vision_agent import read_meter_from_image, VisionExtractionError
from core.web3_oracle import anchor_reading_to_solana, SolanaOracleError
from core.notifier import send_audit_notification, NotificationError

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
)
logger = logging.getLogger("ecotrust.orchestrator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    settings = get_settings()
    logger.info("==================================================")
    logger.info(f"🌿 Starting {settings.APP_NAME} v{settings.APP_VERSION}")
    logger.info(f"⚡ Solana RPC: {settings.SOLANA_RPC_URL}")
    logger.info(f"🤖 Gemini Vision: {'Configured' if settings.GEMINI_API_KEY else 'MOCK Fallback'}")
    logger.info(f"💬 Telegram Bot: {'Configured' if settings.TELEGRAM_BOT_TOKEN else 'MOCK Fallback'}")
    logger.info("==================================================")
    yield
    logger.info("🛑 Shutting down EcoTrust Oracle Orchestrator...")


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "Physical Oracle bridging physical industrial meters and Solana Devnet. "
        "Extracts readings via Gemini 1.5 Flash Vision, generates deterministic SHA-256 hashes, "
        "anchors on-chain via the native Solana Memo Program, and delivers instant Telegram ESG certificates."
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
    }


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """
    Evaluates system integration readiness:
    - Gemini Vision configuration
    - Solana Devnet RPC accessibility
    - Telegram Notifier credentials
    """
    gemini_ready = bool(settings.GEMINI_API_KEY) or settings.VISION_MOCK_FALLBACK
    solana_ready = True  # RPC fallback handles connectivity
    telegram_ready = bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_ID) or settings.NOTIFIER_MOCK_FALLBACK

    return HealthResponse(
        status="ok",
        version=settings.APP_VERSION,
        gemini_ready=gemini_ready,
        solana_ready=solana_ready,
        telegram_ready=telegram_ready,
        network="solana-devnet",
    )


@app.post(
    "/api/v1/audit-meter",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Oracle Audit"],
    summary="Full Physical-to-Blockchain Audit Pipeline",
    description=(
        "Uploads a meter photograph, extracts numerical readings using Gemini 1.5 Flash Vision, "
        "computes a deterministic SHA-256 hash, anchors proof on Solana Devnet via the Memo program, "
        "and dispatches an ESG compliance certificate to Telegram."
    ),
)
async def audit_meter(
    file: UploadFile = File(..., description="High-resolution photograph of the industrial meter dial/screen"),
    meter_hint: Optional[str] = Form(None, description="Optional context (e.g. 'Main boiler gas flowmeter')"),
    telegram_chat_id: Optional[str] = Form(None, description="Optional Telegram chat ID override for alerts"),
):
    start_time = time.perf_counter()

    # Validate file type
    content_type = file.content_type or "image/jpeg"
    if not content_type.startswith("image/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{content_type}'. Please upload an image file (e.g. image/jpeg, image/png).",
        )

    try:
        image_bytes = await file.read()
        if len(image_bytes) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty (0 bytes).",
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to read image stream: {exc}",
        )

    # Step 1: AI Vision Extraction (Developer 1 Module)
    try:
        logger.info(f"📸 [Pipeline Step 1/3] Processing meter image '{file.filename}' ({len(image_bytes)} bytes)")
        reading: MeterReading = await read_meter_from_image(
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

    # Step 2: Web3 Cryptographic Anchoring (Developer 2 Module)
    try:
        logger.info(f"⛓ [Pipeline Step 2/3] Anchoring reading on Solana Devnet: {reading.value} {reading.unit}")
        oracle_proof = await anchor_reading_to_solana(reading)
    except SolanaOracleError as err:
        logger.error(f"Web3 Oracle failed: {err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Solana Devnet anchoring error: {err}",
        )

    # Step 3: Telegram Notification Dispatch (Developer 3 Module)
    try:
        logger.info(f"📨 [Pipeline Step 3/3] Sending ESG audit notification to Telegram...")
        notification = await send_audit_notification(
            reading=reading,
            solscan_url=oracle_proof.solscan_url,
            data_hash=oracle_proof.data_hash,
            chat_id=telegram_chat_id,
        )
    except NotificationError as err:
        logger.warning(f"Notification error: {err}")
        # Partial success: The on-chain proof was still created!
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return AuditResponse(
            status="partial_success",
            reading=reading,
            oracle_proof=oracle_proof,
            notification={
                "sent": False,
                "channel": "telegram",
                "recipient": telegram_chat_id or settings.TELEGRAM_CHAT_ID,
                "message_id": None,
                "is_mock": False,
                "error": str(err),
            },
            execution_time_ms=elapsed_ms,
        )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info(f"🏁 [Pipeline Complete] Audit finished successfully in {elapsed_ms}ms")

    return AuditResponse(
        status="success",
        reading=reading,
        oracle_proof=oracle_proof,
        notification=notification,
        execution_time_ms=elapsed_ms,
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
        "and anchors proof directly to Solana Devnet without requiring camera image processing."
    ),
)
async def audit_sensor(
    reading: MeterReading,
    telegram_chat_id: Optional[str] = None,
):
    """
    Ingests telemetry directly from connected IoT devices/sensors, bypassing computer vision.
    Demonstrates true modularity: any data source can be anchored to Solana.
    """
    start_time = time.perf_counter()
    logger.info(
        f"🔌 [Sensor Ingest] Received telemetry from device '{reading.device_id or 'anonymous'}': "
        f"{reading.value} {reading.unit} (source: {reading.source})"
    )

    # Automatically set source to iot_sensor if left as default ai_vision
    if reading.source == "ai_vision":
        reading.source = "iot_sensor"

    # Step 1: Web3 Cryptographic Anchoring (Developer 2 Module)
    try:
        oracle_proof = await anchor_reading_to_solana(reading)
    except SolanaOracleError as err:
        logger.error(f"Web3 Oracle failed: {err}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Solana Devnet anchoring error: {err}",
        )

    # Step 2: Telegram Notification Dispatch (Developer 3 Module)
    try:
        notification = await send_audit_notification(
            reading=reading,
            solscan_url=oracle_proof.solscan_url,
            data_hash=oracle_proof.data_hash,
            chat_id=telegram_chat_id,
        )
    except NotificationError as err:
        logger.warning(f"Notification error: {err}")
        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
        return AuditResponse(
            status="partial_success",
            reading=reading,
            oracle_proof=oracle_proof,
            notification={
                "sent": False,
                "channel": "telegram",
                "recipient": telegram_chat_id or settings.TELEGRAM_CHAT_ID,
                "message_id": None,
                "is_mock": False,
                "error": str(err),
            },
            execution_time_ms=elapsed_ms,
        )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    logger.info(f"🏁 [Sensor Pipeline Complete] Telemetry anchored in {elapsed_ms}ms")

    return AuditResponse(
        status="success",
        reading=reading,
        oracle_proof=oracle_proof,
        notification=notification,
        execution_time_ms=elapsed_ms,
    )


@app.post(
    "/api/v1/audit-meter-mock",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Oracle Audit"],
    summary="Mock Pipeline Execution (No Image Required)",
    description="Allows rapid frontend or integration testing with synthetic meter reading data.",
)
async def audit_meter_mock(
    custom_reading: Optional[MeterReading] = None,
    telegram_chat_id: Optional[str] = Form(None),
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

    oracle_proof = await anchor_reading_to_solana(custom_reading)
    notification = await send_audit_notification(
        reading=custom_reading,
        solscan_url=oracle_proof.solscan_url,
        data_hash=oracle_proof.data_hash,
        chat_id=telegram_chat_id,
    )

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
    return AuditResponse(
        status="success",
        reading=custom_reading,
        oracle_proof=oracle_proof,
        notification=notification,
        execution_time_ms=elapsed_ms,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
