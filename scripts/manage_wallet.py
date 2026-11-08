"""
EcoTrust Oracle - Solana Devnet Wallet Management Tool (Developer 2)
Allows generating, funding, and checking balances of the Oracle's signing keypair on Solana Devnet.
"""

import sys
import json
import asyncio
import argparse
from pathlib import Path
from typing import Optional

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solana.rpc.async_api import AsyncClient

WALLET_FILE = Path("oracle-devnet.json")
DEFAULT_RPC_URL = "https://api.devnet.solana.com"


def load_or_create_wallet(force: bool = False) -> tuple[Keypair, bool]:
    """
    Loads keypair from oracle-devnet.json or generates a new one.
    Returns: (keypair, was_created)
    """
    if WALLET_FILE.exists() and not force:
        try:
            with open(WALLET_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            keypair = Keypair.from_bytes(bytes(data))
            return keypair, False
        except Exception as e:
            print(f"⚠️ Error reading {WALLET_FILE}: {e}. Generating new keypair.")

    # Generate new keypair
    keypair = Keypair()
    raw_bytes = list(bytes(keypair))
    with open(WALLET_FILE, "w", encoding="utf-8") as f:
        json.dump(raw_bytes, f)

    return keypair, True


def update_env_file(b58_secret: str):
    """Updates or sets SOLANA_PRIVATE_KEY in .env file."""
    env_path = Path(".env")
    if not env_path.exists():
        example_path = Path(".env.example")
        if example_path.exists():
            content = example_path.read_text(encoding="utf-8")
        else:
            content = ""
    else:
        content = env_path.read_text(encoding="utf-8")

    lines = content.splitlines()
    found = False
    new_lines = []
    for line in lines:
        if line.startswith("SOLANA_PRIVATE_KEY="):
            new_lines.append(f"SOLANA_PRIVATE_KEY={b58_secret}")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"\nSOLANA_PRIVATE_KEY={b58_secret}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print("📝 Updated .env with SOLANA_PRIVATE_KEY automatically!")


def cmd_generate(args):
    """Generates a new dedicated Oracle keypair."""
    keypair, was_created = load_or_create_wallet(force=args.force)
    pubkey = keypair.pubkey()
    b58_secret = str(keypair)

    status = "Created NEW" if was_created else "Loaded EXISTING"
    print("\n" + "=" * 60)
    print(f"🔑 ECOTRUST ORACLE DEVNET WALLET ({status})")
    print("=" * 60)
    print(f"📍 Public Key (Address):")
    print(f"   {pubkey}\n")
    print(f"🔐 Private Key (Base58):")
    print(f"   {b58_secret}\n")
    print(f"💾 File Saved to:")
    print(f"   {WALLET_FILE.resolve()}")
    print("=" * 60)

    update_env_file(b58_secret)

    print("\n👉 SIGUIENTE PASO (FONDEAR CON SOL GRATIS):")
    print(f"1. Abre en tu navegador: https://faucet.solana.com/")
    print(f"2. Conecta tu GitHub (para evitar límites de IP).")
    print(f"3. Pega tu Public Key:")
    print(f"   {pubkey}")
    print(f"4. Solicita 2 o 5 Devnet SOL.")
    print(f"5. Luego ejecuta: uv run python scripts/manage_wallet.py balance\n")


async def _async_balance(pubkey: Pubkey, rpc_url: str):
    print(f"🔍 Conectando a Solana Devnet ({rpc_url})...")
    client = AsyncClient(rpc_url)
    try:
        resp = await client.get_balance(pubkey)
        lamports = resp.value
        sol = lamports / 1_000_000_000

        print("\n" + "=" * 60)
        print("👛 ESTADO DE LA BILLETERA DEL ORÁCULO")
        print("=" * 60)
        print(f"📍 Dirección: {pubkey}")
        print(f"💰 Saldo    : {sol:.6f} SOL ({lamports:,} lamports)")
        print(f"🌐 Red      : Solana Devnet")

        if lamports == 0:
            print("\n⚠️ SALDO EN CERO:")
            print(f"Solicita fondos gratuitos en: https://faucet.solana.com/")
            print(f"Dirección a fondear: {pubkey}")
        elif lamports < 10_000_000:
            print(f"\n💡 Saldo bajo pero suficiente para ~{(lamports // 5000):,} transacciones de memo!")
        else:
            print(f"\n✅ ¡Billetera fondeada y lista! Puedes procesar ~{(lamports // 5000):,} auditorías on-chain.")
        print("=" * 60 + "\n")
    except Exception as e:
        print(f"❌ Error al consultar balance: {e}")
    finally:
        await client.close()


def cmd_balance(args):
    """Checks the Devnet balance of the Oracle wallet."""
    if not WALLET_FILE.exists():
        print(f"❌ Wallet file {WALLET_FILE} not found. Run 'generate' first:")
        print("   uv run python scripts/manage_wallet.py generate")
        return

    keypair, _ = load_or_create_wallet(force=False)
    pubkey = keypair.pubkey()
    rpc_url = args.rpc or DEFAULT_RPC_URL
    asyncio.run(_async_balance(pubkey, rpc_url))


async def _async_airdrop(pubkey: Pubkey, rpc_url: str):
    client = AsyncClient(rpc_url)
    print(f"💧 Solicitando 1 SOL de airdrop para {pubkey}...")
    try:
        resp = await client.request_airdrop(pubkey, 1_000_000_000)
        sig = resp.value
        print(f"✅ ¡Airdrop enviado! Firma de la transacción: {sig}")
        print("⏳ Esperando confirmación...")
        await asyncio.sleep(3)
        bal_resp = await client.get_balance(pubkey)
        print(f"💰 Nuevo Saldo: {bal_resp.value / 1e9:.4f} SOL")
    except Exception as e:
        print(f"⚠️ El airdrop directo por RPC falló (típico rate-limit de IP pública): {e}")
        print(f"\n👉 Usa el Web Faucet oficial que no tiene límite de IP:")
        print(f"   1. Entra a: https://faucet.solana.com/")
        print(f"   2. Conecta tu GitHub")
        print(f"   3. Pega tu dirección: {pubkey}")
    finally:
        await client.close()


def cmd_airdrop(args):
    """Attempts requesting 1 SOL airdrop via RPC."""
    keypair, _ = load_or_create_wallet(force=False)
    pubkey = keypair.pubkey()
    rpc_url = args.rpc or DEFAULT_RPC_URL
    asyncio.run(_async_airdrop(pubkey, rpc_url))


def main():
    parser = argparse.ArgumentParser(description="Gestor de Billetera Solana para EcoTrust Oracle")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Subcomando: generate
    gen_parser = subparsers.add_parser("generate", help="Generar una nueva keypair para el oráculo")
    gen_parser.add_argument("--force", action="store_true", help="Sobrescribir keypair existente")

    # Subcomando: balance
    bal_parser = subparsers.add_parser("balance", help="Consultar saldo en Solana Devnet")
    bal_parser.add_argument("--rpc", default=DEFAULT_RPC_URL, help="URL del RPC de Solana")

    # Subcomando: airdrop
    air_parser = subparsers.add_parser("airdrop", help="Intentar airdrop de 1 SOL por RPC")
    air_parser.add_argument("--rpc", default=DEFAULT_RPC_URL, help="URL del RPC de Solana")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "balance":
        cmd_balance(args)
    elif args.command == "airdrop":
        cmd_airdrop(args)


if __name__ == "__main__":
    main()
