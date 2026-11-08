"""Offline tests for the visible AI reasoning: per-read rationale and the reads list in VisionAnalysis."""

import queue
from types import SimpleNamespace

import pytest

import core.vision_agent as va
from core.schemas import MeterReading


def _fake_reads(monkeypatch, *responses):
    """Each _sync_vision_call returns (or raises) the next response; threads may take them in any order."""
    pending = queue.Queue()
    for r in responses:
        pending.put(r)

    def fake_call(**_):
        r = pending.get_nowait()
        if isinstance(r, BaseException):
            raise r
        return dict(r)

    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY="AIzaX", VISION_MOCK_FALLBACK=False))
    monkeypatch.setattr(va, "_sync_vision_call", fake_call)


def _read(value, rationale="Rodillos negros 0-4-8-2-1, rodillo rojo 7: 4821.7 m3", unit="m3"):
    return {"value": value, "unit": unit, "confidence": 0.95, "obstruction_ratio": 0.0,
            "meter_type": "cyclometer", "model": "gemini-x", "rationale": rationale}


@pytest.mark.asyncio
async def test_unanimous_reads_expose_three_reads_and_winner_rationale(monkeypatch):
    _fake_reads(monkeypatch, *[_read(4821.7)] * 3)
    reading, analysis = await va.analyze_meter_image(b"img")
    assert reading.value == 4821.7
    assert len(analysis.reads) == 3
    assert all(r.value == 4821.7 and r.unit == "m3" and r.error is None for r in analysis.reads)
    assert analysis.rationale == "Rodillos negros 0-4-8-2-1, rodillo rojo 7: 4821.7 m3"


@pytest.mark.asyncio
async def test_split_vote_keeps_dissenting_read(monkeypatch):
    _fake_reads(monkeypatch, _read(4821.7, "mayoria"), _read(4821.7, "mayoria"), _read(482.17, "disidente"))
    reading, analysis = await va.analyze_meter_image(b"img")
    assert reading.value == 4821.7 and analysis.votes == 2
    assert analysis.rationale == "mayoria"
    assert sorted((r.value, r.rationale) for r in analysis.reads) == [
        (482.17, "disidente"), (4821.7, "mayoria"), (4821.7, "mayoria")
    ]


@pytest.mark.asyncio
async def test_failed_read_reported_without_key_leak(monkeypatch):
    secret = "AIzaSySECRETSECRET"
    _fake_reads(
        monkeypatch,
        _read(4821.7), _read(4821.7),
        RuntimeError(f"403 Forbidden for url https://x.googleapis.com/v1?key={secret}"),
    )
    _, analysis = await va.analyze_meter_image(b"img")
    failed = [r for r in analysis.reads if r.error]
    assert len(analysis.reads) == 3 and len(failed) == 1
    assert failed[0].error.startswith("RuntimeError: 403 Forbidden")
    assert failed[0].value is None
    assert secret not in analysis.model_dump_json()


@pytest.mark.asyncio
async def test_read_without_value_reported_as_error(monkeypatch):
    _fake_reads(monkeypatch, _read(4821.7), _read(4821.7), {"unit": "m3", "confidence": 0.9})
    _, analysis = await va.analyze_meter_image(b"img")
    assert [r.error for r in analysis.reads].count("respuesta sin valor numerico") == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("rationale, expected", [
    ("  " + "x" * 500 + "  ", "x" * va.RATIONALE_MAX_CHARS),
    (None, None),
    (12345, None),
    ("   ", None),
])
async def test_rationale_truncated_or_none(monkeypatch, rationale, expected):
    raw = _read(4821.7, rationale)
    if rationale is None:
        raw.pop("rationale")
    _fake_reads(monkeypatch, raw, raw, raw)
    _, analysis = await va.analyze_meter_image(b"img")
    assert analysis.rationale == expected
    assert all(r.rationale == expected for r in analysis.reads)


@pytest.mark.asyncio
async def test_mock_path_has_no_rationale_or_reads(monkeypatch):
    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY="", VISION_MOCK_FALLBACK=True))
    _, analysis = await va.analyze_meter_image(b"img")
    assert analysis.is_mock and analysis.rationale is None and analysis.reads == []


@pytest.mark.asyncio
async def test_meter_reading_contract_unchanged(monkeypatch):
    _fake_reads(monkeypatch, *[_read(4821.7)] * 3)
    reading, _ = await va.analyze_meter_image(b"img")
    assert set(reading.model_dump().keys()) == {"value", "unit", "confidence", "timestamp", "source", "device_id"}
    assert set(MeterReading.model_fields) == {"value", "unit", "confidence", "timestamp", "source", "device_id"}
