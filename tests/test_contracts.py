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
    """Simulated fallback proof keeps the hash contract and is clearly marked (offline: no RPC call)."""
    reading = MeterReading(
        value=500.12,
        unit="kWh",
        confidence=0.99,
        timestamp="2026-11-08T01:00:00Z",
    )
    proof: OracleProof = await anchor_reading_to_solana(reading, force_simulated=True)
    assert proof.data_hash == compute_meter_hash(reading)
    assert proof.is_simulated and proof.solscan_url == "" and proof.tx_signature.startswith("SIMULATED-")
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
async def test_notifier_multiple_chat_ids(monkeypatch):
    """Comma-separated chat IDs each get the message; one failure does not block the others."""
    import core.notifier as notifier

    sent_to = []

    def fake_send(token, chat_id, text):
        sent_to.append(chat_id)
        if chat_id == "222":
            raise notifier.NotificationError("chat not found")
        return {"ok": True, "result": {"message_id": int(chat_id)}}

    monkeypatch.setattr(notifier, "_sync_telegram_send", fake_send)
    monkeypatch.setattr(notifier.get_settings(), "TELEGRAM_BOT_TOKEN", "test-token")

    reading = MeterReading(value=1.0, unit="kWh", confidence=1.0, timestamp="2026-11-08T01:20:00Z")
    result = await send_audit_notification(reading, "https://solscan.io/tx/x", chat_id="111, 222,333")

    assert sent_to == ["111", "222", "333"]
    assert result.sent is True and result.is_mock is False
    assert result.recipient == "111,333"
    assert "222: chat not found" in result.error


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
    # The mock endpoint never writes to Solana
    assert data["oracle_proof"]["is_simulated"] is True and data["oracle_proof"]["solscan_url"] == ""
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
    proof = data["oracle_proof"]
    assert proof["solscan_url"] == "" if proof["is_simulated"] else "solscan.io/tx" in proof["solscan_url"]
    assert "EcoTrust:v1:" in data["oracle_proof"]["memo_payload"]


@pytest.mark.parametrize(
    "key, provider",
    [
        ("AIzaSyExample", "gemini"),
        ("AQ.Ab8RN6Example", "gemini"),
        ("sk-ant-api03-example", "claude"),  # must not be mistaken for DeepSeek
        ("sk-0123456789abcdef", "deepseek"),
    ],
)
def test_vision_provider_detected_from_key(key, provider):
    from core.vision_agent import detect_provider

    assert detect_provider(key)[0] == provider


def test_vision_unknown_key_is_rejected():
    from core.vision_agent import detect_provider, VisionExtractionError

    with pytest.raises(VisionExtractionError):
        detect_provider("gsk_not_supported")


@pytest.mark.parametrize("key, expected_url_part", [("AIzaX", "googleapis.com"), ("sk-X", "deepseek.com"), ("sk-ant-X", None)])
def test_vision_call_routes_to_provider_and_parses_json(monkeypatch, key, expected_url_part):
    """Each key reaches its provider, and fenced JSON from the model is still parsed."""
    from types import SimpleNamespace
    import core.vision_agent as va

    calls = {}
    reply = '```json\n{"value": 12.5, "unit": "bar", "confidence": 0.9}\n```'
    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY=key, VISION_MODEL=None))
    monkeypatch.setattr(va, "_call_claude", lambda *a: calls.setdefault("claude", a) and reply)
    monkeypatch.setattr(va, "_call_openai_compatible", lambda url, *a: calls.setdefault("url", url) and (reply, "used-model"))

    raw = va._sync_vision_call(b"img")
    assert raw["value"] == 12.5
    assert raw["model"]  # the model that answered is reported
    if expected_url_part:
        assert expected_url_part in calls["url"] and "claude" not in calls
    else:
        assert "claude" in calls and "url" not in calls


@pytest.mark.parametrize(
    "raw, expected",
    [
        ({"confidence": 0.95, "obstruction_ratio": 0.10}, 0.95),  # clean dial: model score kept
        ({"confidence": 0.95, "obstruction_ratio": 0.30}, 0.95),  # exactly 30%: not over the limit
        ({"confidence": 0.95, "obstruction_ratio": 0.31}, 0.69),  # >30% glare/dust: capped below 0.70
        ({"confidence": 0.50, "obstruction_ratio": 0.80}, 0.50),  # already low: untouched
        ({"confidence": 0.95, "obstruction_ratio": float("nan")}, 0.69),
        ({"confidence": 1.7}, 1.0),
        ({"confidence": -0.2}, 0.0),
        ({"confidence": float("nan")}, 0.0),
        ({}, 0.0),
    ],
)
def test_vision_confidence_heuristic(raw, expected):
    from core.vision_agent import _calibrate_confidence

    assert _calibrate_confidence(raw) == expected


@pytest.mark.asyncio
async def test_vision_gemini_output_keeps_meter_reading_contract(monkeypatch):
    """Extra Gemini fields must not leak into MeterReading, and obstruction must cap confidence."""
    from types import SimpleNamespace
    import core.vision_agent as va

    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY="test", VISION_MOCK_FALLBACK=False))
    monkeypatch.setattr(
        va,
        "_sync_vision_call",
        lambda **_: {
            "value": "4821.37",
            "unit": "m3",
            "confidence": 0.93,
            "obstruction_ratio": 0.45,
            "meter_type": "cyclometer",
            "timestamp": "1999-01-01T00:00:00Z",  # a model-invented time must be ignored
        },
    )

    reading = await read_meter_from_image(b"img", "image/jpeg")
    data = reading.model_dump()

    assert set(data) == {"value", "unit", "confidence", "timestamp", "source", "device_id"}
    assert isinstance(data["value"], float) and data["value"] == 4821.37
    assert isinstance(data["unit"], str) and data["unit"] == "m3"
    assert isinstance(data["confidence"], float) and data["confidence"] < 0.70
    assert isinstance(data["timestamp"], str) and not data["timestamp"].startswith("1999")
    datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))


@pytest.mark.asyncio
async def test_vision_missing_value_is_rejected(monkeypatch):
    from types import SimpleNamespace
    import core.vision_agent as va

    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY="test", VISION_MOCK_FALLBACK=False))
    monkeypatch.setattr(va, "_sync_vision_call", lambda **_: {"unit": "kWh", "confidence": 0.9})

    with pytest.raises(va.VisionExtractionError):
        await read_meter_from_image(b"img", "image/jpeg")


@pytest.mark.asyncio
async def test_vision_api_failure_never_returns_fake_reading(monkeypatch):
    """With a key configured, an API failure must raise, even if VISION_MOCK_FALLBACK is on."""
    from types import SimpleNamespace
    import core.vision_agent as va

    def boom(**_):
        raise TimeoutError("api down")

    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY="AIzaX", VISION_MOCK_FALLBACK=True))
    monkeypatch.setattr(va, "_sync_vision_call", boom)

    with pytest.raises(va.VisionExtractionError):
        await read_meter_from_image(b"img", "image/jpeg")


@pytest.mark.asyncio
async def test_vision_analysis_reports_votes_model_and_type(monkeypatch):
    from types import SimpleNamespace
    import core.vision_agent as va

    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY="AIzaX", VISION_MOCK_FALLBACK=False))
    monkeypatch.setattr(va, "_sync_vision_call", lambda **_: {**_read(4821.7), "meter_type": "cyclometer", "model": "gemini-x"})

    reading, analysis = await va.analyze_meter_image(b"img")
    assert reading.value == 4821.7
    assert (analysis.votes, analysis.total_reads) == (va.CONSENSUS_READS, va.CONSENSUS_READS)
    assert analysis.model == "gemini-x" and analysis.meter_type == "cyclometer"
    assert analysis.obstruction_ratio == 0.0 and analysis.is_mock is False


def test_api_audit_meter_exposes_vision_analysis():
    files = {"file": ("meter.jpg", b"fake-jpeg", "image/jpeg")}
    vision = client.post("/api/v1/audit-meter", files=files).json()["vision"]
    assert vision["is_mock"] is True  # conftest blanks the key, so the flagged mock is used


@pytest.mark.parametrize(
    "status_code, used",
    [(503, "gemini-flash-lite-latest"), (429, "gemini-flash-lite-latest"), ("timeout", "gemini-flash-lite-latest"), (200, "gemini-flash-latest")],
)
def test_gemini_falls_back_to_lite_when_busy(monkeypatch, status_code, used):
    import requests
    import core.vision_agent as va

    calls = []

    def fake_post(url, **kwargs):
        model = url.split("/models/")[1].split(":")[0]
        calls.append(model)
        assert "key=" not in url and kwargs["headers"]["x-goog-api-key"] == "AIzaX"
        ok = model == va.GEMINI_FALLBACK_MODEL or status_code == 200
        if not ok and status_code == "timeout":
            raise requests.Timeout("hung")
        return SimpleResponse(200 if ok else status_code, {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]})

    monkeypatch.setattr(requests, "post", fake_post)
    _, got = va._call_gemini_native("AIzaX", "gemini-1.5-flash", "p", "b64", "image/jpeg")  # retired name -> default
    assert calls[0] == "gemini-flash-latest" and got == used


class SimpleResponse:
    def __init__(self, status_code, data):
        self.status_code, self._data, self.ok = status_code, data, status_code < 400

    def json(self):
        return self._data

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError(self.status_code)


def _read(value, confidence=0.98, unit="kWh"):
    return {"value": value, "unit": unit, "confidence": confidence, "obstruction_ratio": 0.0}


@pytest.mark.parametrize(
    "results, value, max_confidence, votes",
    [
        ([_read(4821.7), _read(4821.7, 0.95), _read(4821.7)], 4821.7, 0.95, 3),  # unanimous: lowest confidence kept
        ([_read(4821.7), _read(482.17), _read(4821.7)], 4821.7, 0.69, 2),  # 10x misread outvoted, flagged for review
        ([_read(4821.7), _read(482.17), _read(421.7)], None, 0.30, 1),  # no majority
        ([_read(4821.7), TimeoutError("api"), _read(4821.7)], 4821.7, 0.69, 2),  # a failed call counts as dissent
        ([_read(4821.7), _read(4821.7, unit="m3"), _read(4821.7)], 4821.7, 0.69, 2),  # unit disagreement counts
        ([_read(4821.7), {"unit": "kWh"}, _read("NaN"), ], 4821.7, 0.30, 1),  # unusable reads count as dissent
    ],
)
def test_vision_consensus(results, value, max_confidence, votes):
    from core.vision_agent import _consensus

    raw, confidence, got_votes = _consensus(results)
    assert got_votes == votes
    assert confidence <= max_confidence
    if value is not None:
        assert raw["value"] == value


def test_vision_consensus_all_failed_raises_original_error():
    from core.vision_agent import _consensus

    with pytest.raises(TimeoutError):
        _consensus([TimeoutError("a"), ValueError("b"), {"unit": "kWh"}])
