"""
EcoTrust Oracle - Web3 Oracle Module (Developer 2)
Computes deterministic cryptographic hashes of verified meter readings,
anchors them to Solana Devnet via the native Memo Program, and returns
the verifiable Solscan proof URL for corporate ESG compliance.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from typing import Dict, Any, Union, Optional

import requests

from solders.pubkey import Pubkey
from solders.keypair import Keypair
from solders.instruction import Instruction, AccountMeta
from solders.message import Message
from solders.transaction import Transaction
from solana.rpc.async_api import AsyncClient

from core.config import get_settings
from core.schemas import MeterReading, OracleProof, VerifyResult

logger = logging.getLogger("ecotrust.web3")

MEMO_PREFIX = "EcoTrust:v1:"
SIMULATED_PREFIX = "SIMULATED-"


class SolanaOracleError(Exception):
    """Raised when on-chain anchoring fails or wallet is misconfigured."""
    pass


def canonical_json(reading: Union[MeterReading, Dict[str, Any]]) -> str:
    """
    Returns the exact UTF-8 string that is SHA-256 hashed for a reading:
    the canonical dict serialized with sorted keys and no whitespace.
    Anyone holding this string can recompute data_hash independently.
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

    return json.dumps(canonical_dict, sort_keys=True, separators=(",", ":"))


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
    payload = canonical_json(reading)
    sha256_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    logger.debug(f"[Web3Oracle] Computed SHA-256: {sha256_hash} for payload: {payload}")
    return sha256_hash


def _load_or_generate_keypair() -> tuple[Keypair, bool]:
    """
    Loads keypair from environment SOLANA_PRIVATE_KEY (base58 or JSON int array),
    or from local oracle-devnet.json. Generates a transient keypair if none is found.

    Returns:
        tuple[Keypair, bool]: (keypair, is_transient)
    """
    from pathlib import Path
    settings = get_settings()
    pk_str = (settings.SOLANA_PRIVATE_KEY or "").strip()

    if not pk_str:
        # Check local file fallback
        local_wallet = Path("oracle-devnet.json")
        if local_wallet.exists():
            try:
                raw_bytes = json.loads(local_wallet.read_text(encoding="utf-8"))
                logger.info(f"🔑 [Web3Oracle] Loaded keypair from local file: {local_wallet}")
                return Keypair.from_bytes(bytes(raw_bytes)), False
            except Exception as e:
                logger.warning(f"⚠️ [Web3Oracle] Error reading {local_wallet}: {e}")

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
    canonical: str,
    reason: str,
) -> OracleProof:
    """
    Builds an unmistakably simulated proof: it was never broadcast, so it carries
    no explorer link and its signature cannot be confused with a real one.
    """
    logger.warning(f"[Web3Oracle] SIMULATED proof (NOT anchored on Solana): {reason}")
    return OracleProof(
        data_hash=data_hash,
        tx_signature=f"{SIMULATED_PREFIX}{uuid.uuid4().hex}",
        solscan_url="",
        memo_payload=memo_payload,
        network="solana-devnet",
        is_simulated=True,
        slot=None,
        canonical_json=canonical,
        signer=None,
    )


def _sha256_text(canonical: str) -> str:
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def anchor_reading_to_solana(
    reading: Union[MeterReading, Dict[str, Any]],
    force_simulated: bool = False,
    client: Optional[AsyncClient] = None,
    compliance: Optional[Any] = None,
) -> OracleProof:
    """
    Cryptographically anchors the meter reading onto Solana Devnet.
    Canonicalizes the reading and delegates to anchor_payload, so the hash and
    memo are sha256(canonical_json(reading)) and "EcoTrust:v1:<hash>".

    Args:
        reading: MeterReading instance or dict.
        force_simulated: Return a simulated proof without touching the RPC or wallet
            (used for synthetic/mock readings that must never be anchored).
        client: Optional existing AsyncClient connection.
        compliance: Optional ESGCompliance; its status is appended to the memo as an on-chain tag.
    """
    tag = getattr(compliance, "status", None) if compliance is not None else None
    return await anchor_payload(canonical_json(reading), force_simulated=force_simulated, client=client, memo_tag=tag)


async def anchor_payload(
    canonical: str,
    force_simulated: bool = False,
    client: Optional[AsyncClient] = None,
    memo_tag: Optional[str] = None,
) -> OracleProof:
    """
    Anchors any canonical UTF-8 string (a reading, a bill check...) onto Solana Devnet.

    Workflow:
    1. Compute SHA-256 of the canonical string.
    2. Format memo string payload: "EcoTrust:v1:<hash>".
    3. Construct a Solana transaction calling the native Memo Program.
    4. Sign and broadcast transaction on Solana Devnet.
    5. Return Solscan URL and proof metadata (canonical_json = canonical).
    """
    settings = get_settings()
    data_hash = _sha256_text(canonical)
    # Optional status tag (e.g. ":EXCEEDED"); verification only compares the part before ":".
    memo_payload = f"{MEMO_PREFIX}{data_hash}:{memo_tag}" if memo_tag else f"{MEMO_PREFIX}{data_hash}"

    if force_simulated:
        return _generate_simulated_proof(
            data_hash=data_hash,
            memo_payload=memo_payload,
            canonical=canonical,
            reason="force_simulated=True (synthetic reading, never anchored)",
        )

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
                    canonical=canonical,
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

        logger.info(f"🚀 [Web3Oracle] Broadcasted to Solana Devnet! Signature: {tx_signature}")
        logger.info(f"🔗 Solscan Proof URL: {solscan_url}")

        # Await on-chain confirmation (sub-second on Solana)
        try:
            logger.info("⏳ [Web3Oracle] Awaiting on-chain confirmation on Devnet...")
            from solders.signature import Signature
            sig_obj = Signature.from_string(tx_signature)
            await client.confirm_transaction(sig_obj, commitment="confirmed")
            logger.info(f"✅ [Web3Oracle] Transaction confirmed on-chain!")
        except Exception as confirm_err:
            # The tx was broadcast; it is still a real (unconfirmed) anchor, not a simulation.
            logger.warning(
                f"[Web3Oracle] Tx {tx_signature} broadcast but confirmation not observed in time "
                f"({confirm_err}). Returned as REAL, UNCONFIRMED; check it with verify_anchor."
            )

        return OracleProof(
            data_hash=data_hash,
            tx_signature=tx_signature,
            solscan_url=solscan_url,
            memo_payload=memo_payload,
            network="solana-devnet",
            is_simulated=False,
            slot=None,
            canonical_json=canonical,
            signer=str(keypair.pubkey()),
        )

    except Exception as exc:
        logger.error(f"❌ [Web3Oracle] Error anchoring on Solana: {exc}", exc_info=True)
        if settings.WEB3_MOCK_FALLBACK:
            return _generate_simulated_proof(
                data_hash=data_hash,
                memo_payload=memo_payload,
                canonical=canonical,
                reason=f"RPC connection or transaction failure: {exc}",
            )
        raise SolanaOracleError(f"Failed to anchor proof to Solana Devnet: {exc}") from exc

    finally:
        if should_close_client:
            await client.close()


# ---------------------------------------------------------------------------
# Independent verification
# ---------------------------------------------------------------------------

_VERIFY_CHECKS = ("tx_found", "tx_succeeded", "memo_found", "hash_matches", "signer_matches")


def _rpc_get_transaction(rpc_url: str, tx_signature: str) -> Optional[Dict[str, Any]]:
    """
    Synchronous JSON-RPC getTransaction call. Returns the `result` object, or None
    when the transaction is not found. Raises on transport or RPC-level errors.
    """
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTransaction",
        "params": [
            tx_signature,
            {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"},
        ],
    }
    resp = requests.post(rpc_url, json=body, timeout=15.0)
    resp.raise_for_status()
    data = resp.json()
    if data.get("error"):
        err = data["error"]
        raise SolanaOracleError(f"RPC error {err.get('code')}: {err.get('message')}")
    return data.get("result")


def _extract_memo_hash(tx: Dict[str, Any], memo_program_id: str) -> Optional[str]:
    """Returns the hash after 'EcoTrust:v1:' in the first EcoTrust memo instruction, if any."""
    message = (tx.get("transaction") or {}).get("message") or {}
    instructions = list(message.get("instructions") or [])
    for inner in (tx.get("meta") or {}).get("innerInstructions") or []:
        instructions.extend(inner.get("instructions") or [])
    for ix in instructions:
        if not isinstance(ix, dict) or ix.get("programId") != memo_program_id:
            continue
        text = ix.get("parsed")
        if isinstance(text, str) and text.startswith(MEMO_PREFIX):
            raw = text[len(MEMO_PREFIX):].strip()
            return raw.split(":")[0] if ":" in raw else raw
    return None


def _extract_fee_payer(tx: Dict[str, Any]) -> Optional[str]:
    keys = (((tx.get("transaction") or {}).get("message") or {}).get("accountKeys")) or []
    if not keys:
        return None
    first = keys[0]
    return first.get("pubkey") if isinstance(first, dict) else str(first)


async def verify_anchor(reading: MeterReading, tx_signature: str) -> VerifyResult:
    """
    Independently re-checks that `reading` was anchored by this oracle in `tx_signature`:
    recomputes the canonical JSON and delegates to verify_payload.
    """
    return await verify_payload(canonical_json(reading), tx_signature)


async def verify_payload(canonical: str, tx_signature: str) -> VerifyResult:
    """
    Independently re-checks that the canonical string was anchored by this oracle in
    `tx_signature`: recomputes SHA-256, fetches the transaction from the RPC and compares
    the EcoTrust memo hash and the fee payer. Never raises.
    """
    tx_signature = str(tx_signature or "").strip()
    canonical = canonical if isinstance(canonical, str) else str(canonical)
    try:
        return await _verify_payload(canonical, tx_signature)
    except Exception as exc:
        logger.warning(f"[Web3Oracle] verify_payload unexpected failure for {tx_signature}: {type(exc).__name__}")
        return VerifyResult(
            valid=False,
            tx_signature=tx_signature,
            computed_hash=_sha256_text(canonical),
            canonical_json=canonical,
            checks={name: False for name in _VERIFY_CHECKS},
            detail=f"Verificacion fallida: error inesperado ({type(exc).__name__}).",
        )


async def _verify_payload(canonical: str, tx_signature: str) -> VerifyResult:
    settings = get_settings()
    computed = _sha256_text(canonical)
    checks = {name: False for name in _VERIFY_CHECKS}

    def result(detail: str, memo_hash=None, signer=None, expected=None) -> VerifyResult:
        return VerifyResult(
            valid=all(checks.values()),
            tx_signature=tx_signature,
            computed_hash=computed,
            canonical_json=canonical,
            memo_hash=memo_hash,
            signer=signer,
            expected_signer=expected,
            checks=dict(checks),
            detail=detail,
        )

    if tx_signature.startswith(SIMULATED_PREFIX):
        return result(
            "Firma SIMULADA: esta prueba nunca se envio a Solana, por lo que no existe en la cadena "
            "y no puede verificarse."
        )

    keypair, is_transient = _load_or_generate_keypair()
    expected_signer = None if is_transient else str(keypair.pubkey())

    try:
        tx = await asyncio.to_thread(_rpc_get_transaction, settings.SOLANA_RPC_URL, tx_signature)
    except Exception as exc:
        # The RPC URL may embed an API key (e.g. Helius ?api-key=), keep it out of logs/responses.
        msg = str(exc).replace(settings.SOLANA_RPC_URL, "<rpc>") if settings.SOLANA_RPC_URL else str(exc)
        logger.warning(f"[Web3Oracle] verify_anchor RPC failure for {tx_signature}: {msg}")
        return result(f"No se pudo consultar el RPC de Solana: {msg}", expected=expected_signer)

    if not tx:
        return result(
            "Transaccion no encontrada en Solana Devnet (no existe o aun no esta confirmada).",
            expected=expected_signer,
        )
    checks["tx_found"] = True
    checks["tx_succeeded"] = (tx.get("meta") or {}).get("err") is None

    memo_hash = _extract_memo_hash(tx, settings.SOLANA_MEMO_PROGRAM_ID)
    checks["memo_found"] = memo_hash is not None
    checks["hash_matches"] = memo_hash is not None and memo_hash.lower() == computed.lower()

    signer = _extract_fee_payer(tx)
    checks["signer_matches"] = expected_signer is not None and signer == expected_signer

    if all(checks.values()):
        detail = "Verificacion correcta: los datos coinciden con el hash anclado en Solana por este oraculo."
    else:
        problems = []
        if not checks["tx_succeeded"]:
            problems.append("la transaccion fallo en la cadena")
        if not checks["memo_found"]:
            problems.append("no contiene un memo EcoTrust:v1")
        elif not checks["hash_matches"]:
            problems.append("el hash del memo no coincide con los datos enviados")
        if expected_signer is None:
            problems.append("el oraculo no tiene una billetera fija configurada para comparar el firmante")
        elif not checks["signer_matches"]:
            problems.append("el firmante no es la billetera de este oraculo")
        detail = "Verificacion fallida: " + "; ".join(problems) + "."
    return result(detail, memo_hash=memo_hash, signer=signer, expected=expected_signer)
