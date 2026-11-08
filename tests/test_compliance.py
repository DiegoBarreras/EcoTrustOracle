"""
Tests for ESG Compliance Threshold Verification on Net Consumption.
Ensures that:
1. `consumption` (current reading - previous reading) is strictly the value evaluated against the threshold.
2. If consumption > threshold, flags `EXCEEDED` / breach with excess percentage.
3. If consumption <= threshold, flags `COMPLIANT`.
4. Solana memo payload reflects compliance status on-chain.
5. Telegram notification reflects breach warnings or compliance status.
"""

import pytest
from core.schemas import MeterReading, evaluate_compliance, ESGCompliance
from core.web3_oracle import anchor_reading_to_solana
from core.notifier import format_telegram_audit_message
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_evaluate_compliance_compliant():
    # Net consumption = 80 kWh, Threshold = 100 kWh -> Compliant
    comp = evaluate_compliance(consumption=80.0, threshold=100.0, unit="kWh")
    assert comp is not None
    assert comp.is_breach is False
    assert comp.status == "COMPLIANT"
    assert comp.consumption == 80.0
    assert comp.threshold == 100.0
    assert comp.excess_percentage is None
    assert "dentro del umbral" in comp.detail


def test_evaluate_compliance_breach():
    # Net consumption = 150 kWh, Threshold = 100 kWh -> Exceeded by +50%
    comp = evaluate_compliance(consumption=150.0, threshold=100.0, unit="kWh")
    assert comp is not None
    assert comp.is_breach is True
    assert comp.status == "EXCEEDED"
    assert comp.consumption == 150.0
    assert comp.threshold == 100.0
    assert comp.excess_percentage == 50.0
    assert "superó el umbral mensual esperado" in comp.detail


def test_evaluate_compliance_requires_consumption():
    # User requirement: consumption must be the value compared against threshold.
    # If consumption is None, compliance cannot be evaluated.
    assert evaluate_compliance(consumption=None, threshold=100.0) is None
    assert evaluate_compliance(consumption=50.0, threshold=None) is None
    assert evaluate_compliance(consumption=50.0, threshold=0.0) is None


@pytest.mark.asyncio
async def test_solana_memo_payload_with_compliance():
    reading = MeterReading(
        value=500.0,
        unit="kWh",
        confidence=0.98,
        timestamp="2026-11-08T08:00:00Z",
    )
    compliance_breach = ESGCompliance(
        threshold=100.0,
        consumption=200.0,
        is_breach=True,
        excess_percentage=100.0,
        status="EXCEEDED",
        detail="Over limit",
    )
    proof = await anchor_reading_to_solana(reading, force_simulated=True, compliance=compliance_breach)
    assert ":EXCEEDED" in proof.memo_payload
    assert proof.memo_payload.startswith("EcoTrust:v1:")


def test_telegram_message_formatting_breach():
    reading = MeterReading(
        value=500.0,
        unit="kWh",
        confidence=0.98,
        timestamp="2026-11-08T08:00:00Z",
        device_id="ASSET-01",
    )
    comp = evaluate_compliance(consumption=250.0, threshold=200.0, unit="kWh")
    msg = format_telegram_audit_message(
        reading,
        solscan_url="https://solscan.io/tx/fake?cluster=devnet",
        data_hash="abc123hash",
        is_simulated=False,
        consumption=250.0,
        compliance=comp,
    )
    assert "ALERTA DE INCUMPLIMIENTO ESG" in msg
    assert "UMBRAL MENSUAL EXCEDIDO (+25.0%)" in msg
    assert "250.0 kWh" in msg
    assert "200.0 kWh" in msg


def test_api_audit_sensor_with_threshold():
    body = {
        "value": 1350.0,
        "unit": "kWh",
        "confidence": 0.99,
        "timestamp": "2026-11-08T08:30:00Z",
        "source": "iot_sensor",
        "device_id": "METER-FACTORY-01",
    }
    # previous_value = 1000.0 -> consumption = 350.0
    # monthly_threshold = 300.0 -> consumption (350) > threshold (300) -> EXCEEDED (+16.7%)
    res = client.post("/api/v1/audit-sensor?previous_value=1000.0&monthly_threshold=300.0", json=body)
    assert res.status_code == 201
    data = res.json()
    assert data["consumption"] == 350.0
    assert data["compliance"] is not None
    assert data["compliance"]["is_breach"] is True
    assert data["compliance"]["status"] == "EXCEEDED"
    assert data["compliance"]["excess_percentage"] == 16.7
    assert ":EXCEEDED" in data["oracle_proof"]["memo_payload"]
