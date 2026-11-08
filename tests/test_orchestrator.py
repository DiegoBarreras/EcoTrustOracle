"""Orchestrator (main.py) behavior: upload guards, counter check, simulated-only paths, verify wiring."""

from fastapi.testclient import TestClient

import main
from core.schemas import VerifyResult

client = TestClient(main.app)

READING = {"value": 120.5, "unit": "kWh", "confidence": 1.0, "timestamp": "2026-11-08T02:00:00Z", "device_id": "M-1"}


def test_counter_below_previous_is_anchored_but_flagged():
    res = client.post("/api/v1/audit-sensor", params={"previous_value": 200}, json={**READING, "device_id": "FLAG-1"})

    assert res.status_code == 201
    data = res.json()
    assert data["comparison"]["anomaly"] == "reading_below_previous"
    assert data["comparison"]["consumption"] == -79.5
    assert data["oracle_proof"]["data_hash"]  # still anchored as evidence
    history = client.get("/api/v1/devices/FLAG-1/history").json()
    assert history["entries"][-1]["anomaly"] == "reading_below_previous"


def test_backwards_reading_is_not_judged_compliant():
    res = client.post(
        "/api/v1/audit-sensor", params={"previous_value": 1000, "monthly_threshold": 100}, json={**READING, "device_id": "BACK-1"}
    )
    data = res.json()
    assert data["comparison"]["anomaly"] == "reading_below_previous"
    assert data["compliance"] is None


def test_counter_reports_consumption():
    res = client.post("/api/v1/audit-sensor", params={"previous_value": 100}, json={**READING, "device_id": "CONS-1"})
    assert res.status_code == 201
    assert res.json()["consumption"] == 20.5
    assert res.json()["comparison"]["previous"]["origin"] == "client"


def test_history_drives_comparison_and_limits():
    dev = "HIST-1"
    first = {**READING, "device_id": dev, "value": 1000, "timestamp": "2026-11-01T00:00:00Z"}
    assert client.post("/api/v1/audit-sensor", json=first).json()["comparison"] is None

    limit = client.put(f"/api/v1/devices/{dev}/limit", json={"period": "month", "limit": 100, "unit": "kWh"})
    assert limit.status_code == 200 and limit.json()["limit"]["limit"] == 100

    second = {**READING, "device_id": dev, "value": 1090, "timestamp": "2026-11-02T00:00:00Z"}
    data = client.post("/api/v1/audit-sensor", json=second).json()
    assert data["comparison"]["previous"]["origin"] == "history"
    assert data["comparison"]["previous"]["value"] == 1000
    assert data["comparison"]["consumption"] == 90
    assert data["limit_status"]["status"] in ("warning", "exceeded")

    devices = {d["device_id"]: d for d in client.get("/api/v1/devices").json()}
    assert devices[dev]["count"] == 2
    assert client.delete(f"/api/v1/devices/{dev}/limit").status_code == 204
    assert client.delete(f"/api/v1/devices/{dev}/limit").status_code == 404


def test_synthetic_readings_stay_out_of_history():
    client.post("/api/v1/audit-meter-mock", json={**READING, "device_id": "MOCK-DEV"})
    client.post("/api/v1/audit-meter", files={"file": ("a.jpg", b"img", "image/jpeg")}, data={"device_id": "MOCK-DEV"})
    assert client.get("/api/v1/devices/MOCK-DEV/history").json()["entries"] == []


def test_bill_check_offline_mock_flow():
    files = {"bill": ("bill.jpg", b"bill-bytes", "image/jpeg")}
    res = client.post("/api/v1/bill-check", files=files)
    assert res.status_code == 201, res.text
    data = res.json()
    assert data["bill"]["is_mock"] is True
    assert data["verdict"] in ("consistent", "discrepancies", "inconclusive")
    assert data["checks"] and data["explanation"]
    assert data["oracle_proof"]["is_simulated"] is True  # synthetic bill never anchored for real
    assert data["canonical_json"]


def test_bill_check_rejects_bad_files():
    assert client.post("/api/v1/bill-check", files={"bill": ("a.svg", b"<svg/>", "image/svg+xml")}).status_code == 415


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


def test_verify_payload_endpoint_delegates(monkeypatch):
    async def fake_verify(canonical, tx):
        return VerifyResult(valid=False, tx_signature=tx, computed_hash="h", canonical_json=canonical, detail="no")

    monkeypatch.setattr(main, "verify_payload", fake_verify)
    res = client.post("/api/v1/verify-payload", json={"canonical_json": '{"a":1}', "tx_signature": "y" * 64})
    assert res.status_code == 200 and res.json()["canonical_json"] == '{"a":1}'
