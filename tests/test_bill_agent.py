"""Offline tests of core/bill_agent.py: no provider is ever called (every model call is monkeypatched)."""

import hashlib
import json
import threading
from types import SimpleNamespace

import pytest

import core.bill_agent as ba
import core.vision_agent as va
from core.schemas import BillCheckResult, BillExtraction, BillFields, MeterReading

KEY = SimpleNamespace(VISION_API_KEY="AIzaX", VISION_MODEL=None, VISION_MOCK_FALLBACK=False)
NO_KEY = SimpleNamespace(VISION_API_KEY="", VISION_MODEL=None, VISION_MOCK_FALLBACK=True)

GOOD = {
    "provider": "CFE", "account_number": "1234-5678 90", "meter_serial": "F2K-3A1",
    "period_start": "2026-09-01", "period_end": "2026-10-31",
    "previous_reading": 12000, "current_reading": 12480, "billed_consumption": 480,
    "unit": "kWh", "total_amount": 1440.0, "currency": "MXN", "reading_type": "actual",
    "notes": "  Tarifa domestica 1  ", "model": "gemini-x",
}


def _reads(monkeypatch, responses, settings=KEY):
    """Each bill read returns (or raises) the next response; threads may take them in any order."""
    lock, queue = threading.Lock(), list(responses)
    seen = []

    def fake_call(**kwargs):
        seen.append(kwargs)
        with lock:
            item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return dict(item)

    monkeypatch.setattr(ba, "get_settings", lambda: settings)
    monkeypatch.setattr(va, "_sync_vision_call", fake_call)
    return seen


# --------------------------------------------------------------------------- extraction / consensus

@pytest.mark.asyncio
async def test_all_reads_agree_keeps_every_field(monkeypatch):
    seen = _reads(monkeypatch, [GOOD, {**GOOD, "account_number": "1234567890", "provider": " cfe "}, GOOD])
    bill = await ba.extract_bill(b"bill", "image/png")
    assert bill.disputed == [] and bill.votes == 3 and bill.total_reads == 3 and not bill.is_mock
    assert bill.fields.current_reading == 12480.0 and bill.fields.unit == "kWh" and bill.fields.reading_type == "actual"
    assert bill.fields.account_number in ("1234-5678 90", "1234567890")  # spaces/dashes ignored for agreement
    assert bill.fields.provider.casefold() == "cfe"
    assert bill.model == "gemini-x" and bill.notes == "Tarifa domestica 1"
    assert bill.image_sha256 == hashlib.sha256(b"bill").hexdigest()
    assert all(k["system"] == ba.BILL_INSTRUCTION and k["mime_type"] == "image/png" for k in seen)


@pytest.mark.asyncio
async def test_disagreement_discards_field(monkeypatch):
    _reads(monkeypatch, [GOOD, {**GOOD, "total_amount": 1540.0, "meter_serial": "F2K3A7"}, GOOD])
    bill = await ba.extract_bill(b"bill", "image/jpeg")
    assert bill.fields.total_amount is None and bill.fields.meter_serial is None
    assert set(bill.disputed) == {"total_amount", "meter_serial"}
    assert bill.fields.current_reading == 12480.0


@pytest.mark.asyncio
async def test_null_everywhere_is_not_disputed_but_partial_null_is(monkeypatch):
    _reads(monkeypatch, [{**GOOD, "meter_serial": None, "reading_type": None}, {**GOOD, "meter_serial": None}, {**GOOD, "meter_serial": None}])
    bill = await ba.extract_bill(b"bill", "image/jpeg")
    assert bill.fields.meter_serial is None and "meter_serial" not in bill.disputed
    assert bill.fields.reading_type is None and "reading_type" in bill.disputed


@pytest.mark.asyncio
async def test_number_formats_and_tolerance(monkeypatch):
    _reads(monkeypatch, [
        {**GOOD, "total_amount": "1.234,56", "billed_consumption": 480.0, "period_end": "31/10/2026", "unit": "kwh"},
        {**GOOD, "total_amount": "1,234.56", "billed_consumption": 481.0, "period_end": "2026/10/31", "unit": "KWH"},
        {**GOOD, "total_amount": 1234.56, "billed_consumption": 482.0, "period_end": "2026-10-31T00:00:00"},
    ])
    bill = await ba.extract_bill(b"bill", "image/jpeg")
    assert bill.fields.total_amount == 1234.56
    assert bill.fields.billed_consumption == 481.0  # within 0.5 %: median kept
    assert bill.fields.period_end == "2026-10-31" and bill.fields.unit == "kWh" and bill.disputed == []


@pytest.mark.asyncio
async def test_numbers_outside_tolerance_are_disputed(monkeypatch):
    _reads(monkeypatch, [GOOD, {**GOOD, "billed_consumption": 490}, GOOD])  # ~2 % apart
    bill = await ba.extract_bill(b"bill", "image/jpeg")
    assert bill.fields.billed_consumption is None and bill.disputed == ["billed_consumption"]


@pytest.mark.parametrize("text, expected", [
    ("1.234,56", 1234.56), ("1,234.56", 1234.56), ("$ 1 560.00", 1560.0), ("12,5", 12.5),
    ("1,234", 1234.0), ("1.234.567", 1234567.0), ("abc", None), (True, None), (float("nan"), None), (7, 7.0),
])
def test_parse_number(text, expected):
    assert ba.parse_number(text) == expected


@pytest.mark.asyncio
async def test_two_successful_reads_are_enough(monkeypatch):
    _reads(monkeypatch, [GOOD, TimeoutError("down"), GOOD])
    bill = await ba.extract_bill(b"bill", "image/jpeg")
    assert bill.votes == 2 and bill.fields.provider == "CFE"


@pytest.mark.asyncio
async def test_fewer_than_two_reads_raise(monkeypatch):
    _reads(monkeypatch, [GOOD, TimeoutError("down"), ValueError("bad json")])
    with pytest.raises(ba.BillExtractionError):
        await ba.extract_bill(b"bill", "image/jpeg")


@pytest.mark.asyncio
async def test_mock_without_key(monkeypatch):
    def never(**_):
        raise AssertionError("no API call without a key")

    monkeypatch.setattr(ba, "get_settings", lambda: NO_KEY)
    monkeypatch.setattr(va, "_sync_vision_call", never)
    bill = await ba.extract_bill(b"x", "image/jpeg")
    assert bill.is_mock and bill.model == "mock" and bill.fields.provider == "CFE"
    checks, verdict, overcharge, currency = ba.check_bill(bill)
    assert verdict == "discrepancies" and overcharge == 120.0 and currency == "MXN"  # (520-480) * 1560/520


@pytest.mark.asyncio
async def test_no_key_and_no_mock_raises(monkeypatch):
    monkeypatch.setattr(ba, "get_settings", lambda: SimpleNamespace(VISION_API_KEY="your_key", VISION_MOCK_FALLBACK=False))
    with pytest.raises(ba.BillExtractionError):
        await ba.extract_bill(b"x", "image/jpeg")


# --------------------------------------------------------------------------- checks

def _bill(**fields) -> BillExtraction:
    base = dict(
        provider="CFE", meter_serial="F2K3A1", period_start="2026-09-01", period_end="2026-10-31",
        previous_reading=12000.0, current_reading=12480.0, billed_consumption=480.0, unit="kWh",
        total_amount=1440.0, currency="MXN", reading_type="actual",
    )
    base.update(fields)
    return BillExtraction(fields=BillFields(**base), votes=3, total_reads=3, model="m", image_sha256="a" * 64)


def _prev(**fields) -> BillExtraction:
    base = dict(period_start="2026-07-01", period_end="2026-08-31", previous_reading=11550.0,
                current_reading=12000.0, billed_consumption=450.0, total_amount=1350.0)
    base.update(fields)
    return _bill(**base)


def _meter(value, unit="kWh") -> MeterReading:
    return MeterReading(value=value, unit=unit, confidence=0.95, timestamp="2026-11-01T10:00:00Z")


def _by_name(checks):
    return {c.name: c for c in checks}


def test_consistent_bill():
    checks, verdict, overcharge, currency = ba.check_bill(_bill(), _prev(), _meter(12480.4))
    assert {c.status for c in checks} == {"match"} and verdict == "consistent" and overcharge is None
    assert [c.name for c in checks] == [
        "consumption_arithmetic", "reading_type", "meter_vs_bill",
        "continuity", "period_continuity", "consumption_change", "unit_price_change", "meter_serial",
    ]


@pytest.mark.parametrize("billed, status", [(482.4, "match"), (477.7, "match"), (482.5, "mismatch"), (470.0, "mismatch")])
def test_arithmetic_tolerance(billed, status):
    item = _by_name(ba.check_bill(_bill(billed_consumption=billed))[0])["consumption_arithmetic"]
    assert item.status == status and item.expected == "480" and "12480" in item.detail


def test_arithmetic_not_checkable_and_inconclusive():
    checks, verdict, overcharge, _ = ba.check_bill(_bill(previous_reading=None, reading_type=None))
    assert {c.status for c in checks} == {"not_checkable"} and verdict == "inconclusive" and overcharge is None


def test_estimated_reading_is_mismatch():
    item = _by_name(ba.check_bill(_bill(reading_type="estimated"))[0])["reading_type"]
    assert item.status == "mismatch" and "estimo" in item.detail


@pytest.mark.parametrize("value, unit, status", [
    (12480.0, "kWh", "match"), (12479.0, "KWH", "match"), (12478.5, "kWh", "mismatch"), (12480.0, "m3", "not_checkable"),
])
def test_meter_vs_bill(value, unit, status):
    item = _by_name(ba.check_bill(_bill(), meter=_meter(value, unit))[0])["meter_vs_bill"]
    assert item.status == status
    if status == "mismatch":
        assert "posible cobro de mas" in item.detail


def test_previous_bill_checks_only_when_given():
    names = {c.name for c in ba.check_bill(_bill())[0]}
    assert names == {"consumption_arithmetic", "reading_type"}


@pytest.mark.parametrize("prev_current, status", [(12000.0, "match"), (11999.0, "match"), (11900.0, "mismatch"), (None, "not_checkable")])
def test_continuity(prev_current, status):
    assert _by_name(ba.check_bill(_bill(), _prev(current_reading=prev_current))[0])["continuity"].status == status


@pytest.mark.parametrize("prev_end, status", [
    ("2026-08-31", "match"), ("2026-08-29", "match"), ("2026-08-28", "mismatch"), ("2026-09-05", "mismatch"), (None, "not_checkable"),
])
def test_period_continuity(prev_end, status):
    assert _by_name(ba.check_bill(_bill(), _prev(period_end=prev_end))[0])["period_continuity"].status == status


@pytest.mark.parametrize("prev_billed, prev_total, status", [(320.0, 960.0, "match"), (300.0, 900.0, "mismatch"), (None, 900.0, "not_checkable")])
def test_consumption_change(prev_billed, prev_total, status):
    # 480 vs 320 = +50 % exactly (match); vs 300 = +60 % (mismatch)
    assert _by_name(ba.check_bill(_bill(), _prev(billed_consumption=prev_billed, total_amount=prev_total))[0])["consumption_change"].status == status


@pytest.mark.parametrize("prev_total, currency, status", [
    (1350.0, "MXN", "match"),        # 3.00 -> 3.00
    (1174.0, "MXN", "match"),        # ~2.609 -> 3.00 = +14.99 %
    (1170.0, "MXN", "mismatch"),     # 2.60 -> 3.00 = +15.4 %
    (1350.0, "USD", "not_checkable"),
    (None, "MXN", "not_checkable"),
])
def test_unit_price_change(prev_total, currency, status):
    item = _by_name(ba.check_bill(_bill(), _prev(total_amount=prev_total, currency=currency))[0])["unit_price_change"]
    assert item.status == status


@pytest.mark.parametrize("serial, status", [("f2k-3a1", "match"), ("ZZZ999", "mismatch"), (None, "not_checkable")])
def test_meter_serial(serial, status):
    assert _by_name(ba.check_bill(_bill(), _prev(meter_serial=serial))[0])["meter_serial"].status == status


def test_overcharge_takes_max_of_both_sources():
    bill = _bill(billed_consumption=500.0, total_amount=1500.0)  # 20 extra kWh at 3.00 = 60
    _, verdict, overcharge, _ = ba.check_bill(bill, meter=_meter(12450.0))  # meter 30 kWh below = 90
    assert verdict == "discrepancies" and overcharge == 90.0
    _, _, overcharge, _ = ba.check_bill(bill, meter=_meter(12470.0))  # 10 kWh = 30 < 60
    assert overcharge == 60.0


def test_overcharge_none_when_underbilled_or_no_price():
    assert ba.check_bill(_bill(billed_consumption=400.0))[2] is None
    assert ba.check_bill(_bill(billed_consumption=500.0, total_amount=None))[2] is None


# --------------------------------------------------------------------------- explanation

@pytest.mark.asyncio
async def test_explanation_uses_model_text(monkeypatch):
    monkeypatch.setattr(ba, "get_settings", lambda: KEY)
    captured = {}

    def fake_text(system, prompt):
        captured["system"], captured["prompt"] = system, prompt
        return "  **Tu recibo** tiene una discrepancia.  "

    monkeypatch.setattr(va, "_sync_text_call", fake_text)
    bill = _bill(billed_consumption=520.0, total_amount=1560.0)
    checks, verdict, overcharge, currency = ba.check_bill(bill)
    text = await ba.explain_bill_check(checks, verdict, overcharge, currency, bill)
    assert text == "Tu recibo tiene una discrepancia."
    assert "No inventes" in captured["system"] and '"overcharge_estimate": 120.0' in captured["prompt"]


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["raise", "empty", "no_key"])
async def test_explanation_falls_back_to_template(monkeypatch, behavior):
    monkeypatch.setattr(ba, "get_settings", lambda: NO_KEY if behavior == "no_key" else KEY)

    def fake_text(system, prompt):
        if behavior == "raise":
            raise RuntimeError("api down key=SECRET")
        if behavior == "no_key":
            raise AssertionError("no API call without a key")
        return "   "

    monkeypatch.setattr(va, "_sync_text_call", fake_text)
    bill = _bill(billed_consumption=520.0, total_amount=1560.0)
    checks, verdict, overcharge, currency = ba.check_bill(bill)
    text = await ba.explain_bill_check(checks, verdict, overcharge, currency, bill)
    assert text.startswith("Revisamos tu recibo y encontramos discrepancias.")
    assert "120.00 MXN" in text and "SECRET" not in text


# --------------------------------------------------------------------------- canonical json

def test_canonical_json_is_stable_and_excludes_prose():
    bill = _bill(billed_consumption=520.0, total_amount=1560.0)
    bill.notes = "nota del modelo"
    meter = _meter(12480.0)
    checks, verdict, overcharge, currency = ba.check_bill(bill, _prev(), meter)
    result = BillCheckResult(
        bill=bill, previous_bill=_prev(), meter_reading=meter, checks=checks, verdict=verdict,
        overcharge_estimate=overcharge, currency=currency, explanation="texto libre del modelo",
    )
    canon = ba.canonical_bill_json(result)
    parts = {"bill": bill, "previous_bill": _prev(), "meter_reading": meter, "checks": checks,
             "verdict": verdict, "overcharge_estimate": overcharge, "currency": currency}
    assert canon == ba.canonical_bill_json(parts) == ba.canonical_bill_json(result)

    data = json.loads(canon)
    assert canon == json.dumps(data, sort_keys=True, separators=(",", ":"))
    assert "texto libre" not in canon and "nota del modelo" not in canon and "detail" not in canon and "label" not in canon
    assert data["verdict"] == "discrepancies" and data["overcharge_estimate"] == 120.0
    assert data["bill"]["image_sha256"] == "a" * 64 and data["meter_reading"] == meter.to_canonical_dict()
    assert data["checks"][0] == {"name": "consumption_arithmetic", "status": "mismatch", "expected": "480", "actual": "520"}


def test_canonical_json_without_optional_parts():
    bill = _bill()
    checks, verdict, overcharge, currency = ba.check_bill(bill)
    data = json.loads(ba.canonical_bill_json({"bill": bill, "checks": checks, "verdict": verdict,
                                              "overcharge_estimate": overcharge, "currency": currency}))
    assert data["previous_bill"] is None and data["meter_reading"] is None and data["overcharge_estimate"] is None


# --------------------------------------------------------------------------- vision_agent additions

@pytest.mark.parametrize("key", ["AIzaX", "sk-X", "sk-ant-X"])
def test_custom_system_and_text_call_reach_provider(monkeypatch, key):
    calls = []
    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY=key, VISION_MODEL=None))
    monkeypatch.setattr(va, "_call_claude", lambda *a: calls.append(a) or '{"provider": "CFE"}')
    monkeypatch.setattr(va, "_call_openai_compatible", lambda url, *a: calls.append(a) or ('{"provider": "CFE"}', "m"))

    raw = va._sync_vision_call(b"img", system="SYS-BILL", prompt="P-BILL")
    assert raw["provider"] == "CFE" and calls[-1][-1] == "SYS-BILL" and "P-BILL" in calls[-1]
    assert va._sync_text_call("SYS-TXT", "hola") == '{"provider": "CFE"}'
    assert calls[-1][-1] == "SYS-TXT" and calls[-1][3] is None  # no image in a text call


def test_default_system_is_meter_instruction(monkeypatch):
    calls = []
    monkeypatch.setattr(va, "get_settings", lambda: SimpleNamespace(VISION_API_KEY="sk-X", VISION_MODEL=None))
    monkeypatch.setattr(va, "_call_openai_compatible", lambda url, *a: calls.append(a) or ('{"value": 1}', "m"))
    va._sync_vision_call(b"img")
    assert calls[0][-1] == va.SYSTEM_INSTRUCTION


def test_gemini_text_call_has_no_image_and_no_json_mode(monkeypatch):
    import requests

    sent = {}

    class Resp:
        status_code = 200

        def raise_for_status(self):
            pass

        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "hola"}]}}]}

    def fake_post(url, **kwargs):
        sent.update(kwargs["json"])
        return Resp()

    monkeypatch.setattr(requests, "post", fake_post)
    text, _ = va._call_gemini_native("AIzaX", "gemini-flash-latest", "p", None, "text/plain", "SYS")
    assert text == "hola" and sent["system_instruction"]["parts"][0]["text"] == "SYS"
    assert len(sent["contents"][0]["parts"]) == 1 and "response_mime_type" not in sent["generationConfig"]
