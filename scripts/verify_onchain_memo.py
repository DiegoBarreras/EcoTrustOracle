"""
EcoTrust Oracle - On-Chain Verification CLI

Thin wrapper over core.web3_oracle.verify_anchor. Given a transaction signature and
the MeterReading JSON that is claimed to be anchored, it recomputes the canonical JSON
and SHA-256, fetches the transaction from SOLANA_RPC_URL and checks the EcoTrust memo
hash and the oracle signer. The verdict comes only from VerifyResult.valid.

Usage:
    python scripts/verify_onchain_memo.py --tx <signature> --reading reading.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.schemas import MeterReading  # noqa: E402
from core.web3_oracle import verify_anchor  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verificador on-chain de EcoTrust Oracle")
    parser.add_argument("--tx", required=True, help="Firma de la transaccion en Solana (base58)")
    parser.add_argument("--reading", required=True, help="Ruta a un JSON con la MeterReading anclada")
    args = parser.parse_args()

    try:
        raw = json.loads(Path(args.reading).read_text(encoding="utf-8"))
        # Accept either a bare MeterReading or a full audit response containing "reading".
        if isinstance(raw, dict) and isinstance(raw.get("reading"), dict):
            raw = raw["reading"]
        reading = MeterReading(**raw)
    except Exception as exc:
        print(f"No se pudo leer la lectura desde {args.reading}: {exc}")
        return 2

    result = asyncio.run(verify_anchor(reading, args.tx))

    print("=" * 65)
    print("ECOTRUST ORACLE - VERIFICADOR ON-CHAIN")
    print("=" * 65)
    print(f"Transaccion     : {result.tx_signature}")
    print(f"JSON canonico   : {result.canonical_json}")
    print(f"Hash calculado  : {result.computed_hash}")
    print(f"Hash en el memo : {result.memo_hash or '-'}")
    print(f"Firmante        : {result.signer or '-'}")
    print(f"Firmante oraculo: {result.expected_signer or '-'}")
    print("-" * 65)
    for name, ok in result.checks.items():
        print(f"  [{'OK' if ok else 'FALLA'}] {name}")
    print("-" * 65)
    print(result.detail)
    print(f"RESULTADO: {'VALID' if result.valid else 'INVALID'}")
    return 0 if result.valid else 1


if __name__ == "__main__":
    sys.exit(main())
