"""
EcoTrust Oracle - Audit history and consumption limits (SQLite).
A new connection per call keeps this safe to use from FastAPI worker threads.
"""

import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from typing import List, Optional, Set

from core.config import get_settings
from core.schemas import (
    ConsumptionLimit,
    DeviceSummary,
    HistoryEntry,
    MeterReading,
    OracleProof,
    ReadingComparison,
)

_write_lock = threading.Lock()
_initialized: Set[str] = set()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL,
    value REAL,
    unit TEXT,
    timestamp TEXT,
    ts_epoch REAL,
    source TEXT,
    confidence REAL,
    data_hash TEXT,
    tx_signature TEXT,
    is_simulated INTEGER,
    consumption REAL,
    anomaly TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_readings_device_ts ON readings (device_id, ts_epoch);
CREATE TABLE IF NOT EXISTS limits (
    device_id TEXT PRIMARY KEY,
    period TEXT,
    limit_value REAL,
    unit TEXT
);
"""

_ENTRY_COLUMNS = (
    "id, value, unit, timestamp, source, confidence, data_hash, tx_signature, "
    "is_simulated, consumption, anomaly"
)


def _parse_epoch(timestamp: str) -> float:
    try:
        ts = datetime.fromisoformat(timestamp.strip().replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return ts.timestamp()
    except Exception:
        return datetime.now(timezone.utc).timestamp()


def _connect(db_path: Optional[str] = None) -> sqlite3.Connection:
    path = db_path or get_settings().DB_PATH
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    if path not in _initialized:
        with _write_lock:
            if path not in _initialized:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(_SCHEMA)
                conn.commit()
                _initialized.add(path)
    return conn


def _row_to_entry(row: sqlite3.Row) -> HistoryEntry:
    return HistoryEntry(
        id=row["id"],
        value=row["value"],
        unit=row["unit"],
        timestamp=row["timestamp"],
        source=row["source"],
        confidence=row["confidence"],
        data_hash=row["data_hash"],
        tx_signature=row["tx_signature"],
        is_simulated=bool(row["is_simulated"]),
        consumption=row["consumption"],
        anomaly=row["anomaly"],
    )


def save_reading(
    reading: MeterReading,
    proof: OracleProof,
    comparison: Optional[ReadingComparison] = None,
) -> int:
    device_id = (reading.device_id or "").strip()
    if not device_id:
        raise ValueError("device_id es obligatorio para guardar la lectura en el historial")
    params = (
        device_id,
        float(reading.value),
        reading.unit,
        reading.timestamp,
        _parse_epoch(reading.timestamp),
        reading.source,
        float(reading.confidence),
        proof.data_hash,
        proof.tx_signature,
        1 if proof.is_simulated else 0,
        comparison.consumption if comparison else None,
        comparison.anomaly if comparison else None,
        datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    with closing(_connect()) as conn, _write_lock:
        with conn:
            cur = conn.execute(
                "INSERT INTO readings (device_id, value, unit, timestamp, ts_epoch, source, confidence, "
                "data_hash, tx_signature, is_simulated, consumption, anomaly, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                params,
            )
            return int(cur.lastrowid)


def last_reading(device_id: str) -> Optional[HistoryEntry]:
    with closing(_connect()) as conn:
        row = conn.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM readings WHERE device_id = ? "
            "ORDER BY ts_epoch DESC, id DESC LIMIT 1",
            (device_id,),
        ).fetchone()
    return _row_to_entry(row) if row else None


def history(device_id: str, limit: int = 200) -> List[HistoryEntry]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            f"SELECT {_ENTRY_COLUMNS} FROM readings WHERE device_id = ? "
            "ORDER BY ts_epoch DESC, id DESC LIMIT ?",
            (device_id, max(0, int(limit))),
        ).fetchall()
    return [_row_to_entry(r) for r in reversed(rows)]


def devices() -> List[DeviceSummary]:
    with closing(_connect()) as conn:
        rows = conn.execute(
            """
            SELECT r.device_id, r.value, r.unit, r.timestamp, g.cnt, g.anom
            FROM (
                SELECT device_id, COUNT(*) AS cnt,
                       SUM(CASE WHEN anomaly IS NOT NULL THEN 1 ELSE 0 END) AS anom
                FROM readings GROUP BY device_id
            ) g
            JOIN readings r ON r.id = (
                SELECT id FROM readings WHERE device_id = g.device_id
                ORDER BY ts_epoch DESC, id DESC LIMIT 1
            )
            ORDER BY r.ts_epoch DESC, r.id DESC
            """
        ).fetchall()
    return [
        DeviceSummary(
            device_id=r["device_id"],
            last_value=r["value"],
            unit=r["unit"],
            last_timestamp=r["timestamp"],
            count=r["cnt"],
            anomalies=r["anom"] or 0,
        )
        for r in rows
    ]


def set_limit(device_id: str, limit: ConsumptionLimit) -> None:
    with closing(_connect()) as conn, _write_lock:
        with conn:
            conn.execute(
                "INSERT INTO limits (device_id, period, limit_value, unit) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(device_id) DO UPDATE SET period = excluded.period, "
                "limit_value = excluded.limit_value, unit = excluded.unit",
                (device_id, limit.period, float(limit.limit), limit.unit),
            )


def get_limit(device_id: str) -> Optional[ConsumptionLimit]:
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT period, limit_value, unit FROM limits WHERE device_id = ?", (device_id,)
        ).fetchone()
    if not row:
        return None
    return ConsumptionLimit(period=row["period"], limit=row["limit_value"], unit=row["unit"])


def delete_limit(device_id: str) -> bool:
    with closing(_connect()) as conn, _write_lock:
        with conn:
            cur = conn.execute("DELETE FROM limits WHERE device_id = ?", (device_id,))
            return cur.rowcount > 0
