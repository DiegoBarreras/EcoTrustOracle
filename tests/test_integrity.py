"""
EcoTrust Oracle - Integrity & security tests (offline: every RPC/HTTP call is monkeypatched).
"""

import hashlib
import json

import pytest
from solders.keypair import Keypair

import core.notifier as notifier
import core.web3_oracle as web3
from core.notifier import NotificationError, format_telegram_audit_message, send_audit_notification
from core.schemas import MeterReading
from core.web3_oracle import anchor_reading_to_solana, canonical_json, compute_meter_hash, verify_anchor

MEMO_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
SIG = "5" * 88


def _reading(**kw) -> MeterReading:
    base = dict(value=142.85, unit="kWh", confidence=0.98, timestamp="2026-11-08T01:15:31Z", device_id="M-1")
    base.update(kw)
    return MeterReading(**base)


# --- canonical JSON / hash ---------------------------------------------------

def test_canonical_json_is_exact_hashed_string():
    r = _reading()
    cj = canonical_json(r)
    assert cj == (
        '{"confidence":0.98,"device_id":"M-1","source":"ai_vision",'
        '"timestamp":"2026-11-08T01:15:31Z","unit":"KWH","value":142.85}'
    )
    assert compute_meter_hash(r) == hashlib.sha256(cj.encode("utf-8")).hexdigest()
    # dict and model inputs canonicalize identically
    assert canonical_json(r.model_dump()) == cj
    assert compute_meter_hash(r) == compute_meter_hash(_reading())


# --- simulated proofs --------------------------------------------------------

@pytest.mark.asyncio
async def test_force_simulated_never_touches_rpc_or_wallet(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(web3, "_load_or_generate_keypair", boom)
    monkeypatch.setattr(web3, "AsyncClient", boom)
    r = _reading()
    proof = await anchor_reading_to_solana(r, force_simulated=True)
    assert proof.tx_signature.startswith("SIMULATED-")
    assert proof.solscan_url == ""
    assert proof.is_simulated is True
    assert proof.signer is None
    assert proof.canonical_json == canonical_json(r)
    assert proof.memo_payload == f"EcoTrust:v1:{compute_meter_hash(r)}"


# --- verify_anchor -----------------------------------------------------------

def _tx(memo: str, fee_payer: str, err=None) -> dict:
    return {
        "slot": 1,
        "meta": {"err": err, "innerInstructions": []},
        "transaction": {
            "message": {
                "accountKeys": [{"pubkey": fee_payer, "signer": True, "writable": True}],
                "instructions": [{"program": "spl-memo", "programId": MEMO_ID, "parsed": memo}],
            }
        },
    }


@pytest.fixture
def oracle_kp(monkeypatch):
    kp = Keypair()
    monkeypatch.setattr(web3, "_load_or_generate_keypair", lambda: (kp, False))
    return kp


def _patch_rpc(monkeypatch, result=None, exc=None):
    calls = []

    def fake(url, sig):
        calls.append(sig)
        if exc:
            raise exc
        return result

    monkeypatch.setattr(web3, "_rpc_get_transaction", fake)
    return calls


@pytest.mark.asyncio
async def test_verify_valid(monkeypatch, oracle_kp):
    r = _reading()
    _patch_rpc(monkeypatch, _tx(f"EcoTrust:v1:{compute_meter_hash(r)}", str(oracle_kp.pubkey())))
    res = await verify_anchor(r, SIG)
    assert res.valid is True
    assert all(res.checks.values()) and set(res.checks) == {
        "tx_found", "tx_succeeded", "memo_found", "hash_matches", "signer_matches"
    }
    assert res.memo_hash == res.computed_hash
    assert res.signer == res.expected_signer == str(oracle_kp.pubkey())
    assert res.canonical_json == canonical_json(r)


@pytest.mark.asyncio
async def test_verify_hash_mismatch(monkeypatch, oracle_kp):
    r = _reading()
    _patch_rpc(monkeypatch, _tx(f"EcoTrust:v1:{compute_meter_hash(_reading(value=1.0))}", str(oracle_kp.pubkey())))
    res = await verify_anchor(r, SIG)
    assert res.valid is False
    assert res.checks["memo_found"] and not res.checks["hash_matches"]


@pytest.mark.asyncio
async def test_verify_wrong_signer(monkeypatch, oracle_kp):
    r = _reading()
    _patch_rpc(monkeypatch, _tx(f"EcoTrust:v1:{compute_meter_hash(r)}", str(Keypair().pubkey())))
    res = await verify_anchor(r, SIG)
    assert res.valid is False
    assert res.checks["hash_matches"] and not res.checks["signer_matches"]


@pytest.mark.asyncio
async def test_verify_transient_keypair_cannot_match_signer(monkeypatch):
    kp = Keypair()
    monkeypatch.setattr(web3, "_load_or_generate_keypair", lambda: (kp, True))
    r = _reading()
    _patch_rpc(monkeypatch, _tx(f"EcoTrust:v1:{compute_meter_hash(r)}", str(kp.pubkey())))
    res = await verify_anchor(r, SIG)
    assert res.valid is False and res.expected_signer is None and not res.checks["signer_matches"]


@pytest.mark.asyncio
async def test_verify_tx_not_found(monkeypatch, oracle_kp):
    _patch_rpc(monkeypatch, None)
    res = await verify_anchor(_reading(), SIG)
    assert res.valid is False and res.checks["tx_found"] is False
    assert "no encontrada" in res.detail


@pytest.mark.asyncio
async def test_verify_failed_tx(monkeypatch, oracle_kp):
    r = _reading()
    _patch_rpc(monkeypatch, _tx(f"EcoTrust:v1:{compute_meter_hash(r)}", str(oracle_kp.pubkey()),
                                err={"InstructionError": [0, "Custom"]}))
    res = await verify_anchor(r, SIG)
    assert res.valid is False and res.checks["tx_found"] and not res.checks["tx_succeeded"]


@pytest.mark.asyncio
async def test_verify_rpc_error_is_reported_not_raised(monkeypatch, oracle_kp):
    _patch_rpc(monkeypatch, exc=RuntimeError("boom"))
    res = await verify_anchor(_reading(), SIG)
    assert res.valid is False and "RPC" in res.detail


@pytest.mark.asyncio
async def test_verify_simulated_signature_skips_rpc(monkeypatch, oracle_kp):
    calls = _patch_rpc(monkeypatch, None)
    res = await verify_anchor(_reading(), "SIMULATED-" + "a" * 32)
    assert res.valid is False and calls == []
    assert "SIMULADA" in res.detail and not any(res.checks.values())


# --- notifier ----------------------------------------------------------------

def test_html_escaping_of_values_and_href():
    r = _reading(device_id="<b>A&B")
    url = 'https://solscan.io/tx/x?a=1&b="><script>'
    msg = format_telegram_audit_message(r, url, "f" * 64)
    assert "<b>A&B" not in msg and "&lt;b&gt;A&amp;B" in msg
    assert 'href="https://solscan.io/tx/x?a=1&amp;b=&quot;&gt;&lt;script&gt;"' in msg
    assert "<script>" not in msg
    assert "f" * 64 in msg  # full hash, not truncated


def test_simulated_message_has_no_link_or_onchain_claim():
    msg = format_telegram_audit_message(_reading(), "", "f" * 64, is_simulated=True)
    assert "href" not in msg and "solscan" not in msg.lower()
    assert "SIMULADO - no anclado en Solana" in msg
    assert "verified" not in msg.lower() and "anclada en solana" not in msg.lower()


def _with_creds(monkeypatch, token="123456:SECRET-TOKEN"):
    s = notifier.get_settings()
    monkeypatch.setattr(s, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(s, "TELEGRAM_CHAT_ID", "111,222")
    return token


@pytest.mark.asyncio
async def test_all_recipients_failed_raises_and_redacts_token(monkeypatch):
    token = _with_creds(monkeypatch)

    def fake_send(tok, chat_id, text):
        raise ConnectionError(f"HTTPSConnectionPool: url https://api.telegram.org/bot{tok}/sendMessage failed")

    monkeypatch.setattr(notifier, "_sync_telegram_send", fake_send)
    with pytest.raises(NotificationError) as ei:
        await send_audit_notification(_reading(), "https://solscan.io/tx/x")
    assert token not in str(ei.value) and "<redacted>" in str(ei.value)


@pytest.mark.asyncio
async def test_partial_failure_error_is_redacted(monkeypatch):
    token = _with_creds(monkeypatch)
    texts = []

    def fake_send(tok, chat_id, text):
        texts.append(text)
        if chat_id == "222":
            raise ConnectionError(f"https://api.telegram.org/bot{tok}/sendMessage")
        return {"ok": True, "result": {"message_id": 7}}

    monkeypatch.setattr(notifier, "_sync_telegram_send", fake_send)
    res = await send_audit_notification(_reading(), "", "f" * 64, is_simulated=True)
    assert res.sent is True and res.is_mock is False
    assert token not in res.error and "<redacted>" in res.error
    assert all("SIMULADO" in t and "href" not in t for t in texts)
