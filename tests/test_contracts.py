"""
EcoTrust Oracle - Data Contract & Module Tests
Validates the contracts between Vision Agent, Web3 Oracle, Notifier, and Orchestrator.
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient

from main import app
from core.schemas import MeterReading, OracleProof, NotificationResult, AuditResponse
from core.web3_oracle import compute_meter_hash, anchor_reading_to_solana
from core.notifier import format_telegram_audit_message, send_audit_notification
from core.vision_agent import read_meter_from_image

client = TestClient(app)


def test_meter_reading_contract_validation():
    """Verify that MeterReading enforces strictly the required JSON fields."""
    sample = {
        "value": 142.85,
        "unit": "kWh",
        "confidence": 0.98,
        "timestamp": "2026-11-08T01:15:31Z",
    }
    reading = MeterReading(**sample)
    assert reading.value == 142.85
    assert reading.unit == "kWh"
    assert reading.confidence == 0.98
    assert reading.timestamp == "2026-11-08T01:15:31Z"

    # Verify canonical dict sorting
    canonical = reading.to_canonical_dict()
    assert set(["confidence", "timestamp", "unit", "value", "source"]).issubset(set(canonical.keys()))
    assert list(canonical.keys()) == sorted(list(canonical.keys()))


def test_deterministic_sha256_hash():
    """
    Ensure that identical readings produce identical hashes regardless of
    initial dictionary key ordering.
    """
    payload_a = {"value": 100.5, "unit": "M3", "confidence": 0.95, "timestamp": "2026-11-08T00:00:00Z"}
    payload_b = {"unit": "m3", "timestamp": "2026-11-08T00:00:00Z", "value": 100.5, "confidence": 0.95}

    hash_a = compute_meter_hash(payload_a)
    hash_b = compute_meter_hash(payload_b)

    assert hash_a == hash_b
    assert len(hash_a) == 64  # SHA-256 hex string length


@pytest.mark.asyncio
async def test_web3_oracle_fallback():
    """Verify on-chain anchoring fallback returns a valid Solscan URL and proof."""
    reading = MeterReading(
        value=500.12,
        unit="kWh",
        confidence=0.99,
        timestamp="2026-11-08T01:00:00Z",
    )
    proof: OracleProof = await anchor_reading_to_solana(reading)
    assert proof.data_hash == compute_meter_hash(reading)
    assert "solscan.io/tx" in proof.solscan_url
    assert "cluster=devnet" in proof.solscan_url
    assert proof.network == "solana-devnet"
    assert len(proof.tx_signature) > 10


@pytest.mark.asyncio
async def test_notifier_formatting_and_mock():
    """Verify Telegram message formatting and mock delivery."""
    reading = MeterReading(
        value=350.0,
        unit="kgCO2",
        confidence=0.92,
        timestamp="2026-11-08T01:20:00Z",
    )
    solscan_url = "https://solscan.io/tx/mock-sig?cluster=devnet"
    msg_html = format_telegram_audit_message(reading, solscan_url, "abc123hash")

    assert "ECOTRUST ORACLE" in msg_html
    assert "350.0 kgCO2" in msg_html
    assert solscan_url in msg_html

    result: NotificationResult = await send_audit_notification(reading, solscan_url, "abc123hash")
    assert result.sent is True
    assert result.channel == "telegram"


@pytest.mark.asyncio
async def test_vision_agent_mock_fallback():
    """Verify that Vision Agent safely falls back when no Gemini API key is set."""
    dummy_image = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # Minimal dummy JPEG header
    reading = await read_meter_from_image(dummy_image, "image/jpeg")
    assert isinstance(reading, MeterReading)
    assert reading.value > 0
    assert len(reading.unit) > 0
    assert 0.0 <= reading.confidence <= 1.0


def test_api_health_endpoint():
    """Verify /health returns 200 OK and system status."""
    res = client.get("/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert "network" in data


def test_api_audit_meter_mock():
    """Verify POST /api/v1/audit-meter-mock executes complete pipeline end-to-end."""
    res = client.post("/api/v1/audit-meter-mock")
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "success"
    assert "reading" in data
    assert "oracle_proof" in data
    assert "notification" in data
    assert "solscan.io/tx" in data["oracle_proof"]["solscan_url"]
    assert data["execution_time_ms"] > 0


def test_api_audit_meter_with_image_upload():
    """Verify POST /api/v1/audit-meter handles multipart image uploads."""
    dummy_bytes = b"fake-jpeg-image-content-for-testing"
    files = {"file": ("meter.jpg", dummy_bytes, "image/jpeg")}
    data = {"meter_hint": "Facility Gas Meter #4"}

    res = client.post("/api/v1/audit-meter", files=files, data=data)
    assert res.status_code in (200, 201)
    json_resp = res.json()
    assert json_resp["status"] in ("success", "partial_success")
    assert json_resp["reading"]["value"] > 0
    assert "solscan_url" in json_resp["oracle_proof"]


def test_api_audit_sensor_direct_telemetry():
    """
    Verify POST /api/v1/audit-sensor handles direct telemetry from connected hardware sensors,
    bypassing the vision engine completely while preserving the on-chain anchor.
    """
    telemetry_payload = {
        "value": 1850.45,
        "unit": "m3",
        "confidence": 1.0,
        "timestamp": "2026-11-08T02:00:00Z",
        "source": "iot_sensor",
        "device_id": "MODBUS-FLOW-UNIT-99",
    }
    res = client.post("/api/v1/audit-sensor", json=telemetry_payload)
    assert res.status_code == 201
    data = res.json()
    assert data["status"] == "success"
    assert data["reading"]["value"] == 1850.45
    assert data["reading"]["unit"] == "m3"
    assert data["reading"]["source"] == "iot_sensor"
    assert data["reading"]["device_id"] == "MODBUS-FLOW-UNIT-99"
    assert "solscan.io/tx" in data["oracle_proof"]["solscan_url"]
    assert "EcoTrust:v1:" in data["oracle_proof"]["memo_payload"]
