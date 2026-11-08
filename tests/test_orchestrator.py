"""Orchestrator (main.py) behavior: upload guards, counter check, simulated-only paths, verify wiring."""

from fastapi.testclient import TestClient

import main
from core.schemas import VerifyResult

client = TestClient(main.app)

READING = {"value": 120.5, "unit": "kWh", "confidence": 1.0, "timestamp": "2026-11-08T02:00:00Z", "device_id": "M-1"}


def test_counter_below_previous_is_refused_and_not_anchored(monkeypatch):
    anchored = []
    monkeypatch.setattr(main, "anchor_reading_to_solana", lambda *a, **k: anchored.append(a))

    res = client.post("/api/v1/audit-sensor", params={"previous_value": 200}, json=READING)

    assert res.status_code == 409
    assert res.json()["detail"]["code"] == "reading_below_previous"
    assert anchored == []


def test_counter_reports_consumption():
    res = client.post("/api/v1/audit-sensor", params={"previous_value": 100}, json=READING)
    assert res.status_code == 201
    assert res.json()["consumption"] == 20.5


def test_non_finite_values_are_rejected():
    for bad in ("NaN", "Infinity"):
        res = client.post("/api/v1/audit-sensor", content=f'{{"value": {bad}, "unit": "kWh", "confidence": 1, "timestamp": "2026-11-08T02:00:00Z"}}', headers={"Content-Type": "application/json"})
        assert res.status_code == 422, bad


def test_upload_guards():
    assert client.post("/api/v1/audit-meter", files={"file": ("a.svg", b"<svg/>", "image/svg+xml")}).status_code == 415
    assert client.post("/api/v1/audit-meter", files={"file": ("a.jpg", b"", "image/jpeg")}).status_code == 400
    big = b"0" * (main.MAX_IMAGE_BYTES + 1)
    assert client.post("/api/v1/audit-meter", files={"file": ("a.jpg", big, "image/jpeg")}).status_code == 413


def test_mock_vision_reading_is_never_anchored_for_real():
    # conftest blanks the vision key, so the synthetic reading is used and must stay simulated
    data = client.post("/api/v1/audit-meter", files={"file": ("a.jpg", b"img", "image/jpeg")}, data={"device_id": "BOILER-3"}).json()
    assert data["vision"]["is_mock"] is True
    assert data["oracle_proof"]["is_simulated"] is True
    assert data["reading"]["device_id"] == "BOILER-3"


def test_mock_endpoint_uses_custom_reading_and_is_simulated():
    data = client.post("/api/v1/audit-meter-mock", json=READING).json()
    assert data["reading"]["value"] == 120.5
    assert data["oracle_proof"]["is_simulated"] is True


def test_health_does_not_count_mock_fallbacks_as_ready():
    data = client.get("/health").json()
    assert data["gemini_ready"] is False and data["telegram_ready"] is False


def test_verify_endpoint_delegates_to_verify_anchor(monkeypatch):
    async def fake_verify(reading, tx):
        return VerifyResult(valid=True, tx_signature=tx, computed_hash="h", canonical_json="{}", checks={"hash_matches": True})

    monkeypatch.setattr(main, "verify_anchor", fake_verify)
    res = client.post("/api/v1/verify", json={"reading": READING, "tx_signature": "x" * 64})
    assert res.status_code == 200 and res.json()["valid"] is True
