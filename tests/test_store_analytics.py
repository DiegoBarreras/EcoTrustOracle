"""Tests for core/store.py (SQLite history) and core/analytics.py (comparison and limits)."""

import functools
import threading
from datetime import datetime, timezone

import pytest

from core import analytics, store
from core.schemas import (
    ConsumptionLimit,
    HistoryEntry,
    MeterReading,
    OracleProof,
    PreviousReading,
    ReadingComparison,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _reading(value, ts, unit="kWh", device_id="M-1"):
    return MeterReading(value=value, unit=unit, confidence=0.9, timestamp=ts, device_id=device_id)


def _proof(n=0, simulated=True):
    return OracleProof(
        data_hash=f"{n:064x}",
        tx_signature=f"sig{n}",
        solscan_url=f"https://solscan.io/tx/sig{n}?cluster=devnet",
        memo_payload=f"EcoTrust:v1:{n:064x}",
        is_simulated=simulated,
    )


def _entry(i, value, ts, unit="kWh", anomaly=None):
    return HistoryEntry(
        id=i, value=value, unit=unit, timestamp=ts, source="ai_vision", confidence=0.9,
        data_hash="h", tx_signature="s", is_simulated=True, anomaly=anomaly,
    )


def _prev(value, ts, unit="kWh"):
    return PreviousReading(value=value, unit=unit, timestamp=ts)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "_connect", functools.partial(store._connect, db_path=str(tmp_path / "h.db")))
    return tmp_path


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------

def test_store_round_trip_and_history_order(db):
    assert store.last_reading("M-1") is None
    assert store.history("M-1") == []
    # Inserted out of order: ordering must follow the reading timestamp, not insertion.
    store.save_reading(_reading(110, "2026-11-02T00:00:00Z"), _proof(2))
    store.save_reading(_reading(100, "2026-11-01T00:00:00Z"), _proof(1), None)
    comp = ReadingComparison(previous=_prev(110, "2026-11-02T00:00:00Z"), consumption=-10, anomaly="reading_below_previous")
    rid = store.save_reading(_reading(100, "2026-11-03T00:00:00Z"), _proof(3, simulated=False), comp)
    assert isinstance(rid, int)

    last = store.last_reading("M-1")
    assert last.id == rid and last.value == 100 and last.anomaly == "reading_below_previous"
    assert last.consumption == -10 and last.is_simulated is False and last.tx_signature == "sig3"

    hist = store.history("M-1")
    assert [h.value for h in hist] == [100, 110, 100]
    assert [h.timestamp for h in hist] == ["2026-11-01T00:00:00Z", "2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z"]
    # limit keeps the most recent entries, still oldest first
    assert [h.timestamp for h in store.history("M-1", limit=2)] == ["2026-11-02T00:00:00Z", "2026-11-03T00:00:00Z"]


def test_store_devices_summary(db):
    store.save_reading(_reading(5, "2026-11-01T00:00:00Z", unit="m3", device_id="W-1"), _proof(1))
    store.save_reading(_reading(10, "2026-11-05T00:00:00Z", device_id="M-1"), _proof(2))
    comp = ReadingComparison(previous=_prev(10, "2026-11-05T00:00:00Z"), consumption=-1, anomaly="reading_below_previous")
    store.save_reading(_reading(9, "2026-11-06T00:00:00Z", device_id="M-1"), _proof(3), comp)

    devs = store.devices()
    assert [d.device_id for d in devs] == ["M-1", "W-1"]
    m1, w1 = devs
    assert (m1.count, m1.anomalies, m1.last_value, m1.unit, m1.last_timestamp) == (2, 1, 9, "kWh", "2026-11-06T00:00:00Z")
    assert (w1.count, w1.anomalies, w1.unit) == (1, 0, "m3")


def test_store_limits_upsert_get_delete(db):
    assert store.get_limit("M-1") is None
    store.set_limit("M-1", ConsumptionLimit(period="day", limit=10, unit="kWh"))
    store.set_limit("M-1", ConsumptionLimit(period="month", limit=300, unit="kWh"))
    assert store.get_limit("M-1") == ConsumptionLimit(period="month", limit=300, unit="kWh")
    assert store.delete_limit("M-1") is True
    assert store.delete_limit("M-1") is False
    assert store.get_limit("M-1") is None


@pytest.mark.parametrize("device_id", [None, "", "   "])
def test_store_requires_device_id(db, device_id):
    with pytest.raises(ValueError):
        store.save_reading(_reading(1, "2026-11-01T00:00:00Z", device_id=device_id), _proof())


def test_store_unparsable_timestamp_uses_now(db):
    # MeterReading already normalises bad timestamps; the store must still accept odd stored strings.
    assert store._parse_epoch("not-a-date") == pytest.approx(datetime.now(timezone.utc).timestamp(), abs=5)
    assert store._parse_epoch("2026-11-08T00:00:00Z") == datetime(2026, 11, 8, tzinfo=timezone.utc).timestamp()


def test_store_concurrent_saves(db):
    errors = []

    def worker(t):
        try:
            for i in range(10):
                store.save_reading(_reading(t * 100 + i, f"2026-11-01T{t:02d}:{i:02d}:00Z"), _proof(t * 100 + i))
        except Exception as exc:  # pragma: no cover - surfaced through the assertion below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(8)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert errors == []
    hist = store.history("M-1", limit=1000)
    assert len(hist) == 80
    assert len({h.id for h in hist}) == 80


# ---------------------------------------------------------------------------
# analytics.compare
# ---------------------------------------------------------------------------

def _steady_history(n=4, step=10.0):
    # One reading per day, `step` units per day.
    return [_entry(i, 100 + i * step, f"2026-11-0{i + 1}T00:00:00Z") for i in range(n)]


def test_compare_consumption_elapsed_and_daily_rate():
    c = analytics.compare(_reading(112.5, "2026-11-08T12:00:00Z"), _prev(100, "2026-11-08T00:00:00Z"), [])
    assert c.consumption == 12.5
    assert c.elapsed_hours == 12
    assert c.daily_rate == 25
    assert c.typical_daily_rate is None
    assert c.anomaly is None and c.anomaly_message is None


def test_compare_unparsable_or_non_positive_elapsed():
    c = analytics.compare(_reading(110, "2026-11-08T00:00:00Z"), _prev(100, "garbage"), [])
    assert c.elapsed_hours is None and c.daily_rate is None and c.consumption == 10
    c = analytics.compare(_reading(110, "2026-11-08T00:00:00Z"), _prev(100, "2026-11-08T00:00:00Z"), [])
    assert c.elapsed_hours is None and c.daily_rate is None


def test_compare_reading_below_previous():
    c = analytics.compare(_reading(120.5, "2026-11-08T03:00:00Z"), _prev(500, "2026-11-08T02:00:00Z"), [])
    assert c.anomaly == "reading_below_previous"
    assert c.consumption == -379.5
    assert c.daily_rate is None
    for piece in ("120.5 kWh", "500 kWh", "08/11 02:00 UTC", "Se registro y anclo igualmente"):
        assert piece in c.anomaly_message


def test_compare_unit_mismatch_takes_precedence():
    c = analytics.compare(_reading(50, "2026-11-08T03:00:00Z", unit="L"), _prev(500, "2026-11-08T02:00:00Z", unit="m3"), [])
    assert c.anomaly == "unit_mismatch"
    for piece in ("50 L", "500 m3", "Se registro y anclo igualmente"):
        assert piece in c.anomaly_message


def test_compare_unit_normalisation():
    c = analytics.compare(
        _reading(510, "2026-11-08T03:00:00Z", unit="M3"), _prev(500, "2026-11-08T02:00:00Z", unit=" m³"), []
    )
    assert c.anomaly is None


def test_compare_abnormal_jump():
    hist = _steady_history(4, step=10)  # typical 10/day
    c = analytics.compare(_reading(190, "2026-11-05T00:00:00Z"), _prev(130, "2026-11-04T00:00:00Z"), hist)
    assert c.typical_daily_rate == 10
    assert c.daily_rate == 60
    assert c.anomaly == "abnormal_jump"
    for piece in ("60 kWh", "10 kWh/dia", "Se registro y anclo igualmente"):
        assert piece in c.anomaly_message
    # Exactly 5x is not a jump
    c = analytics.compare(_reading(180, "2026-11-05T00:00:00Z"), _prev(130, "2026-11-04T00:00:00Z"), hist)
    assert c.anomaly is None


def test_compare_below_previous_beats_jump():
    c = analytics.compare(_reading(100, "2026-11-05T00:00:00Z"), _prev(130, "2026-11-04T00:00:00Z"), _steady_history())
    assert c.anomaly == "reading_below_previous"


def test_typical_rate_needs_three_clean_rates():
    hist = _steady_history(3)  # only 2 rates
    c = analytics.compare(_reading(300, "2026-11-04T00:00:00Z"), _prev(120, "2026-11-03T00:00:00Z"), hist)
    assert c.typical_daily_rate is None and c.anomaly is None

    hist = _steady_history(4)
    hist[2] = _entry(2, 120, "2026-11-03T00:00:00Z", anomaly="abnormal_jump")  # excludes two pairs
    c = analytics.compare(_reading(300, "2026-11-05T00:00:00Z"), _prev(130, "2026-11-04T00:00:00Z"), hist)
    assert c.typical_daily_rate is None

    hist = _steady_history(5) + [_entry(9, 50, "2026-11-06T00:00:00Z", unit="L")]
    c = analytics.compare(_reading(150, "2026-11-06T00:00:00Z"), _prev(140, "2026-11-05T00:00:00Z"), hist)
    assert c.typical_daily_rate == 10


# ---------------------------------------------------------------------------
# analytics.period_bounds
# ---------------------------------------------------------------------------

UTC = timezone.utc


def test_period_bounds_day_week_month():
    now = datetime(2026, 11, 8, 15, 30, tzinfo=UTC)  # Sunday
    assert analytics.period_bounds("day", now) == (datetime(2026, 11, 8, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC))
    assert analytics.period_bounds("week", now) == (datetime(2026, 11, 2, tzinfo=UTC), datetime(2026, 11, 9, tzinfo=UTC))
    assert analytics.period_bounds("month", now) == (datetime(2026, 11, 1, tzinfo=UTC), datetime(2026, 12, 1, tzinfo=UTC))


def test_period_bounds_month_december_rollover_and_monday():
    assert analytics.period_bounds("month", datetime(2026, 12, 31, 23, 59, tzinfo=UTC)) == (
        datetime(2026, 12, 1, tzinfo=UTC), datetime(2027, 1, 1, tzinfo=UTC)
    )
    monday = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)
    assert analytics.period_bounds("week", monday)[0] == monday


# ---------------------------------------------------------------------------
# analytics.evaluate_limit
# ---------------------------------------------------------------------------

def _day_limit(limit=100, unit="kWh"):
    return ConsumptionLimit(period="day", limit=limit, unit=unit)


NOW = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)  # half the day elapsed


@pytest.mark.parametrize("last, used, status", [(150, 50, "ok"), (180, 80, "warning"), (220, 120, "exceeded")])
def test_evaluate_limit_status(last, used, status):
    entries = [_entry(1, 100, "2026-11-08T01:00:00Z"), _entry(2, last, "2026-11-08T11:00:00Z")]
    s = analytics.evaluate_limit(_day_limit(), entries, NOW)
    assert s.used == used and s.status == status and s.percent == used
    assert s.period_start == "2026-11-08T00:00:00Z"
    assert s.projected == used * 2


def test_evaluate_limit_nothing_in_period():
    s = analytics.evaluate_limit(_day_limit(), [_entry(1, 100, "2026-11-07T10:00:00Z")], NOW)
    assert s.used == 0 and s.percent == 0 and s.status == "ok"


def test_evaluate_limit_baseline_before_period():
    entries = [_entry(1, 50, "2026-11-06T00:00:00Z"), _entry(2, 100, "2026-11-07T23:00:00Z"), _entry(3, 130, "2026-11-08T06:00:00Z")]
    s = analytics.evaluate_limit(_day_limit(), entries, NOW)
    assert s.used == 30


def test_evaluate_limit_rollback_robust():
    entries = [
        _entry(1, 100, "2026-11-08T01:00:00Z"),
        _entry(2, 140, "2026-11-08T02:00:00Z"),
        _entry(3, 20, "2026-11-08T03:00:00Z", anomaly="reading_below_previous"),
        _entry(4, 30, "2026-11-08T04:00:00Z"),
    ]
    s = analytics.evaluate_limit(_day_limit(), entries, NOW)
    assert s.used == 50


def test_evaluate_limit_unit_filter():
    entries = [
        _entry(1, 100, "2026-11-08T01:00:00Z", unit="M³"),
        _entry(2, 9000, "2026-11-08T02:00:00Z", unit="L"),
        _entry(3, 110, "2026-11-08T03:00:00Z", unit="m3"),
    ]
    s = analytics.evaluate_limit(_day_limit(unit="m3"), entries, NOW)
    assert s.used == 10


def test_evaluate_limit_projection_needs_5_percent_elapsed():
    entries = [_entry(1, 100, "2026-11-08T00:10:00Z"), _entry(2, 101, "2026-11-08T00:20:00Z")]
    early = datetime(2026, 11, 8, 1, 0, tzinfo=UTC)  # ~4.2 % of the day
    assert analytics.evaluate_limit(_day_limit(), entries, early).projected is None
    later = datetime(2026, 11, 8, 2, 24, tzinfo=UTC)  # 10 %
    assert analytics.evaluate_limit(_day_limit(), entries, later).projected == pytest.approx(10)
