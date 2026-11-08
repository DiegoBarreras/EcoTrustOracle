"""
EcoTrust Oracle - Web3 Oracle Module (Developer 2)
Computes deterministic cryptographic hashes of verified meter readings,
anchors them to Solana Devnet via the native Memo Program, and returns
the verifiable Solscan proof URL for corporate ESG compliance.
"""

import hashlib
import json
import logging
from typing import Dict, Any, Union, Optional

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction
from solders.hash import Hash
from solana.rpc.async_api import AsyncClient

from core.config import get_settings
from core.schemas import MeterReading, OracleProof

logger = logging.getLogger("ecotrust.web3")


class SolanaOracleError(Exception):
    """Raised when on-chain anchoring fails or wallet is misconfigured."""
    pass


def compute_meter_hash(reading: Union[MeterReading, Dict[str, Any]]) -> str:
    """
    Computes a deterministic SHA-256 hash from a canonicalized MeterReading payload.
    Ensures that identical readings yield identical cryptographic hashes regardless of
    field order in the original JSON.

    Args:
        reading: MeterReading instance or raw dictionary.

    Returns:
        Hexadecimal SHA-256 digest string.
    """
    if isinstance(reading, MeterReading):
        canonical_dict = reading.to_canonical_dict()
    else:
        # Standardize raw dict keys and numeric precision
        canonical_dict = {
            "confidence": round(float(reading.get("confidence", 0.0)), 4),
            "source": str(reading.get("source", "ai_vision")).strip().lower(),
            "timestamp": str(reading.get("timestamp", "")),
            "unit": str(reading.get("unit", "")).strip().upper(),
            "value": round(float(reading.get("value", 0.0)), 4),
        }
        if reading.get("device_id"):
            canonical_dict["device_id"] = str(reading["device_id"]).strip()

    canonical_json = json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))
    sha256_hash = hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()
    logger.debug(f"🔑 [Web3Oracle] Computed SHA-256: {sha256_hash} for payload: {canonical_json}")
    return sha256_hash


def _load_or_generate_keypair() -> tuple[Keypair, bool]:
    """
    Loads keypair from environment SOLANA_PRIVATE_KEY (base58 or JSON int array).
    Generates a transient keypair if none is configured.

    Returns:
        tuple[Keypair, bool]: (keypair, is_transient)
    """
    settings = get_settings()
    pk_str = (settings.SOLANA_PRIVATE_KEY or "").strip()

    if not pk_str:
        logger.info("ℹ️ [Web3Oracle] No SOLANA_PRIVATE_KEY found; generating transient keypair")
        return Keypair(), True

    try:
        # Attempt Base58 parsing
        return Keypair.from_base58_string(pk_str), False
    except Exception:
        pass

    try:
        # Attempt JSON int array parsing [12, 45, ...]
        raw_list = json.loads(pk_str)
        if isinstance(raw_list, list):
            return Keypair.from_bytes(bytes(raw_list)), False
    except Exception:
        pass

    logger.warning("⚠️ [Web3Oracle] SOLANA_PRIVATE_KEY could not be parsed; falling back to transient keypair")
    return Keypair(), True


def _generate_simulated_proof(
    data_hash: str,
    memo_payload: str,
    keypair: Keypair,
    reason: str,
) -> OracleProof:
    """
    Generates a simulated Devnet proof for hackathon development when
    RPC faucet is rate limited or no funded wallet is configured.
    """
    logger.warning(f"⚠️ [Web3Oracle] Generating SIMULATED Solana proof: {reason}")
    dummy_hash = Hash.default()
    memo_program = Pubkey.from_string(get_settings().SOLANA_MEMO_PROGRAM_ID)
    ix = Instruction(
        program_id=memo_program,
        data=memo_payload.encode("utf-8"),
        accounts=[AccountMeta(pubkey=keypair.pubkey(), is_signer=True, is_writable=True)],
    )
    msg = Message([ix], keypair.pubkey())
    signed_tx = Transaction([keypair], msg, dummy_hash)
    simulated_sig = str(signed_tx.signatures[0])
    solscan_url = f"{get_settings().SOLSCAN_BASE_URL}/{simulated_sig}?cluster=devnet"

    return OracleProof(
        data_hash=data_hash,
        tx_signature=simulated_sig,
        solscan_url=solscan_url,
        memo_payload=memo_payload,
        network="solana-devnet",
        is_simulated=True,
        slot=None,
    )


async def anchor_reading_to_solana(
    reading: Union[MeterReading, Dict[str, Any]],
    client: Optional[AsyncClient] = None,
) -> OracleProof:
    """
    Cryptographically anchors the meter reading onto Solana Devnet.

    Workflow:
    1. Canonicalize reading and compute SHA-256 hash.
    2. Format memo string payload: "GP:v1:<hash>".
    3. Construct a Solana transaction calling the native Memo Program.
    4. Sign and broadcast transaction on Solana Devnet.
    5. Return Solscan URL and proof metadata.

    Args:
        reading: MeterReading instance or dict.
        client: Optional existing AsyncClient connection.

    Returns:
        OracleProof: Validated model containing data_hash, tx_signature, and solscan_url.
    """
    settings = get_settings()
    data_hash = compute_meter_hash(reading)
    memo_payload = f"EcoTrust:v1:{data_hash}"

    keypair, is_transient = _load_or_generate_keypair()
    memo_program_id = Pubkey.from_string(settings.SOLANA_MEMO_PROGRAM_ID)

    should_close_client = False
    if client is None:
        client = AsyncClient(settings.SOLANA_RPC_URL, commitment=settings.SOLANA_COMMITMENT)
        should_close_client = True

    try:
        # Check wallet balance on devnet
        balance_resp = await client.get_balance(keypair.pubkey())
        balance_lamports = balance_resp.value

        logger.info(
            f"👛 [Web3Oracle] Signer: {keypair.pubkey()} | Balance: {balance_lamports} lamports ({balance_lamports / 1e9} SOL)"
        )

        # If zero balance, attempt devnet airdrop (up to 1 SOL) if wallet is transient
        if balance_lamports < 5000:
            if is_transient:
                logger.info("💧 [Web3Oracle] Wallet balance low. Requesting Devnet airdrop (0.5 SOL)...")
                try:
                    airdrop_resp = await client.request_airdrop(keypair.pubkey(), 500_000_000)
                    logger.info(f"💧 Airdrop requested: {airdrop_resp.value}")
                    # Wait briefly for confirmation
                    import asyncio
                    await asyncio.sleep(2.0)
                    bal = await client.get_balance(keypair.pubkey())
                    balance_lamports = bal.value
                except Exception as airdrop_err:
                    logger.warning(f"⚠️ Airdrop request failed (normal on devnet rate limit): {airdrop_err}")

        # If still insufficient funds and mock fallback is allowed, produce simulated proof
        if balance_lamports < 5000:
            if settings.WEB3_MOCK_FALLBACK:
                return _generate_simulated_proof(
                    data_hash=data_hash,
                    memo_payload=memo_payload,
                    keypair=keypair,
                    reason=f"Signer {keypair.pubkey()} has insufficient lamports ({balance_lamports}) for tx fee",
                )
            raise SolanaOracleError(
                f"Wallet {keypair.pubkey()} has insufficient balance ({balance_lamports} lamports) and WEB3_MOCK_FALLBACK is disabled."
            )

        # Fetch latest blockhash
        bh_resp = await client.get_latest_blockhash()
        recent_blockhash = bh_resp.value.blockhash

        # Construct Memo instruction
        # Native Memo Program takes arbitrary bytes data
        instruction = Instruction(
            program_id=memo_program_id,
            data=memo_payload.encode("utf-8"),
            accounts=[
                AccountMeta(pubkey=keypair.pubkey(), is_signer=True, is_writable=True),
            ],
        )

        message = Message([instruction], keypair.pubkey())
        transaction = Transaction([keypair], message, recent_blockhash)

        # Broadcast transaction to Devnet
        send_resp = await client.send_transaction(transaction)
        tx_signature = str(send_resp.value)
        solscan_url = f"{settings.SOLSCAN_BASE_URL}/{tx_signature}?cluster=devnet"

        logger.info(f"🚀 [Web3Oracle] Anchored on Solana Devnet! Signature: {tx_signature}")
        logger.info(f"🔗 Solscan Proof URL: {solscan_url}")

        return OracleProof(
            data_hash=data_hash,
            tx_signature=tx_signature,
            solscan_url=solscan_url,
            memo_payload=memo_payload,
            network="solana-devnet",
            is_simulated=False,
            slot=None,
        )

    except Exception as exc:
        logger.error(f"❌ [Web3Oracle] Error anchoring on Solana: {exc}", exc_info=True)
        if settings.WEB3_MOCK_FALLBACK:
            return _generate_simulated_proof(
                data_hash=data_hash,
                memo_payload=memo_payload,
                keypair=keypair,
                reason=f"RPC connection or transaction failure: {exc}",
            )
        raise SolanaOracleError(f"Failed to anchor proof to Solana Devnet: {exc}") from exc

    finally:
        if should_close_client:
            await client.close()
