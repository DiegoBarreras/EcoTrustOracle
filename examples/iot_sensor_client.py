"""
EcoTrust Oracle - Example IoT Hardware Client
Simulates a physical sensor (e.g. Modbus, Arduino, RS-485 flowmeter)
connected to a computer or edge gateway, streaming real-time readings
directly to the EcoTrust Oracle without passing through the vision engine.
"""

import time
import requests
from datetime import datetime, timezone

ORACLE_API_URL = "http://127.0.0.1:8000/api/v1/audit-sensor"


def stream_sensor_reading(
    value: float,
    unit: str = "kWh",
    device_id: str = "USB-POWERMETER-01",
    confidence: float = 1.0,
):
    """Packages and transmits physical hardware telemetry directly to Solana."""
    payload = {
        "value": value,
        "unit": unit,
        "confidence": confidence,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "iot_sensor",
        "device_id": device_id,
    }

    print(f"📡 Transmitting sensor payload from {device_id}: {value} {unit}...")
    try:
        response = requests.post(ORACLE_API_URL, json=payload, timeout=10.0)
        response.raise_for_status()
        data = response.json()

        print("✅ Anchored on Solana Devnet!")
        print(f"   SHA-256 Digest : {data['oracle_proof']['data_hash']}")
        print(f"   Solscan Proof  : {data['oracle_proof']['solscan_url']}")
        print(f"   Latency        : {data['execution_time_ms']} ms")
        return data
    except Exception as e:
        print(f"❌ Failed to deliver sensor telemetry: {e}")
        return None


if __name__ == "__main__":
    # Example simulated pulse from a hardware meter
    stream_sensor_reading(
        value=314.16,
        unit="m3",
        device_id="SERIAL-GASMETER-COM3",
        confidence=0.999,
    )
