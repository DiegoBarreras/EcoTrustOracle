"""
EcoTrust Oracle - Live Solana Devnet Transaction Tester
Broadcasts a real audit reading to Solana Devnet using the funded keypair.
"""

import sys
import asyncio
from datetime import datetime, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from core.schemas import MeterReading
from core.web3_oracle import anchor_reading_to_solana


async def main():
    reading = MeterReading(
        value=894.20,
        unit="kWh",
        confidence=0.995,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source="iot_sensor",
        device_id="PRIMARY-TRANSFORMER-01",
    )
    print("🚀 Enviando transaccion REAL a Solana Devnet...")
    proof = await anchor_reading_to_solana(reading)
    print("\n" + "=" * 60)
    print("🎉 TRANSACCION CONFIRMADA EN SOLANA DEVNET!")
    print("=" * 60)
    print(f"🔒 SHA-256 Digest : {proof.data_hash}")
    print(f"✍️ Tx Signature   : {proof.tx_signature}")
    print(f"🔍 Solscan URL    : {proof.solscan_url}")
    print(f"⚡ Simulado       : {proof.is_simulated}")
    print("=" * 60 + "\n")
    return proof.tx_signature


if __name__ == "__main__":
    asyncio.run(main())
