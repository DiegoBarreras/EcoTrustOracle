"""
EcoTrust Oracle - Consumption analytics (pure functions, no I/O).
Compares a cumulative meter reading with the previous one and evaluates consumption limits.
"""

import statistics
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from core.schemas import (
    ConsumptionLimit,
    HistoryEntry,
    LimitPeriod,
    LimitStatus,
    MeterReading,
    PreviousReading,
    ReadingComparison,
)

JUMP_FACTOR = 5.0
MIN_TYPICAL_RATES = 3
EVIDENCE_NOTE = "Se registro igualmente como evidencia."


def normalize_unit(unit: str) -> str:
    return (unit or "").lower().replace(" ", "").replace("³", "3")


def _parse_ts(timestamp: str) -> Optional[datetime]:
    try:
        ts = datetime.fromisoformat(timestamp.strip().replace("Z", "+00:00"))
    except Exception:
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def _fmt(value: float) -> str:
    text = f"{round(value, 4):.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def _fmt_ts(timestamp: str) -> str:
    ts = _parse_ts(timestamp)
    return ts.strftime("%d/%m %H:%M UTC") if ts else timestamp


def _hours_between(earlier: str, later: str) -> Optional[float]:
    a, b = _parse_ts(earlier), _parse_ts(later)
    if a is None or b is None:
        return None
    hours = (b - a).total_seconds() / 3600
    return hours if hours > 0 else None


def _typical_daily_rate(history: List[HistoryEntry]) -> Optional[float]:
    rates = []
    for a, b in zip(history, history[1:]):
        if a.anomaly or b.anomaly or normalize_unit(a.unit) != normalize_unit(b.unit):
            continue
        hours = _hours_between(a.timestamp, b.timestamp)
        delta = b.value - a.value
        if hours is None or delta < 0:
            continue
        rates.append(delta / hours * 24)
    return statistics.median(rates) if len(rates) >= MIN_TYPICAL_RATES else None


def compare(reading: MeterReading, previous: PreviousReading, history: List[HistoryEntry]) -> ReadingComparison:
    consumption = round(reading.value - previous.value, 4)
    elapsed = _hours_between(previous.timestamp, reading.timestamp)
    daily_rate = round(consumption / elapsed * 24, 4) if elapsed is not None and consumption >= 0 else None
    ordered = sorted(history, key=lambda e: (_parse_ts(e.timestamp) or datetime.min.replace(tzinfo=timezone.utc), e.id))
    typical = _typical_daily_rate(ordered)
    if typical is not None:
        typical = round(typical, 4)

    prev_when = _fmt_ts(previous.timestamp)
    anomaly = None
    message = None
    if normalize_unit(reading.unit) != normalize_unit(previous.unit):
        anomaly = "unit_mismatch"
        message = (
            f"La lectura {_fmt(reading.value)} {reading.unit} usa una unidad distinta a la anterior "
            f"{_fmt(previous.value)} {previous.unit} ({prev_when}). No se pueden comparar: posible cambio "
            f"de medidor o error de lectura. {EVIDENCE_NOTE}"
        )
    elif consumption < 0:
        anomaly = "reading_below_previous"
        message = (
            f"La lectura {_fmt(reading.value)} {reading.unit} es menor que la anterior "
            f"{_fmt(previous.value)} {previous.unit} ({prev_when}). Un medidor acumulativo no retrocede: "
            f"posible alteracion del medidor o error de lectura. {EVIDENCE_NOTE}"
        )
    elif typical is not None and typical > 0 and daily_rate is not None and daily_rate > JUMP_FACTOR * typical:
        anomaly = "abnormal_jump"
        message = (
            f"El consumo de {_fmt(consumption)} {reading.unit} desde la lectura anterior ({prev_when}) "
            f"equivale a {_fmt(daily_rate)} {reading.unit}/dia, mas de {_fmt(JUMP_FACTOR)} veces lo habitual "
            f"({_fmt(typical)} {reading.unit}/dia). Posible fuga, fallo del equipo o error de lectura. {EVIDENCE_NOTE}"
        )

    return ReadingComparison(
        previous=previous,
        consumption=consumption,
        elapsed_hours=round(elapsed, 4) if elapsed is not None else None,
        daily_rate=daily_rate,
        typical_daily_rate=typical,
        anomaly=anomaly,
        anomaly_message=message,
    )


def period_bounds(period: LimitPeriod, now: datetime) -> Tuple[datetime, datetime]:
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "day":
        return midnight, midnight + timedelta(days=1)
    if period == "week":
        start = midnight - timedelta(days=midnight.weekday())
        return start, start + timedelta(days=7)
    if period == "month":
        start = midnight.replace(day=1)
        if start.month == 12:
            return start, start.replace(year=start.year + 1, month=1)
        return start, start.replace(month=start.month + 1)
    raise ValueError(f"Periodo no soportado: {period}")


def evaluate_limit(limit: ConsumptionLimit, entries: List[HistoryEntry], now: datetime) -> LimitStatus:
    start, end = period_bounds(limit.period, now)
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now.astimezone(timezone.utc)
    unit = normalize_unit(limit.unit)

    timed = []
    for e in entries:
        ts = _parse_ts(e.timestamp)
        if ts is not None and normalize_unit(e.unit) == unit:
            timed.append((ts, e.id, e))
    timed.sort(key=lambda t: (t[0], t[1]))

    before = [e for ts, _, e in timed if ts < start]
    in_period = [e for ts, _, e in timed if start <= ts < end]

    used = 0.0
    if in_period:
        chain = ([before[-1]] if before else []) + in_period
        # Only positive steps count, so a counter rollback or a flagged bad read cannot erase consumption.
        used = sum(max(0.0, b.value - a.value) for a, b in zip(chain, chain[1:]))
    used = round(used, 4)

    percent = round(used / limit.limit * 100, 1)
    status = "exceeded" if percent >= 100 else "warning" if percent >= 80 else "ok"

    fraction = (now - start).total_seconds() / (end - start).total_seconds()
    projected = round(used / fraction, 4) if fraction >= 0.05 else None

    return LimitStatus(
        period=limit.period,
        period_start=start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        limit=limit.limit,
        unit=limit.unit,
        used=used,
        percent=percent,
        status=status,
        projected=projected,
    )
