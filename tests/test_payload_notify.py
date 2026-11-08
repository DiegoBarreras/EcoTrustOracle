"""
EcoTrust Oracle - generic payload anchoring and Telegram alerts (offline: RPC and Telegram are monkeypatched).
"""

import hashlib
import json

import pytest
from solders.keypair import Keypair

import core.notifier as notifier
import core.web3_oracle as web3
from core.notifier import (
    NotificationError,
    format_bill_check_message,
    format_telegram_audit_message,
    send_audit_notification,
    send_bill_check_notification,
)
from core.schemas import (
    BillCheckItem,
    BillCheckResult,
    BillExtraction,
    BillFields,
    LimitStatus,
    MeterReading,
    OracleProof,
    PreviousReading,
    ReadingComparison,
)
from core.web3_oracle import (
    anchor_payload,
    anchor_reading_to_solana,
    canonical_json,
    compute_meter_hash,
    verify_anchor,
    verify_payload,
)

MEMO_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
HOSTILE = "<script>alert('x')</script> & <b>"


def _reading(**kw) -> MeterReading:
    base = dict(value=1234.5, unit="m3", confidence=0.95, timestamp="2026-11-08T01:15:31Z", device_id="MTR-1")
    base.update(kw)
    return MeterReading(**base)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# --- anchor_payload ---------------------------------------------------------

@pytest.mark.asyncio
async def test_anchor_payload_simulated_hash_and_memo(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("must not be called")

    monkeypatch.setattr(web3, "_load_or_generate_keypair", boom)
    monkeypatch.setattr(web3, "AsyncClient", boom)
    canonical = json.dumps({"kind": "bill_check", "verdict": "discrepancies"}, sort_keys=True, separators=(",", ":"))
    proof = await anchor_payload(canonical, force_simulated=True)
    assert proof.data_hash == _sha(canonical)
    assert proof.memo_payload == f"EcoTrust:v1:{_sha(canonical)}"
    assert proof.canonical_json == canonical
    assert proof.is_simulated is True and proof.solscan_url == "" and proof.signer is None
    assert proof.tx_signature.startswith("SIMULATED-")


@pytest.mark.asyncio
async def test_reading_hash_unchanged_through_delegation():
    r = _reading()
    proof = await anchor_reading_to_solana(r, force_simulated=True)
    assert proof.data_hash == compute_meter_hash(r) == _sha(canonical_json(r))
    assert proof.memo_payload == f"EcoTrust:v1:{compute_meter_hash(r)}"
    assert proof.canonical_json == canonical_json(r)


class _Val:
    def __init__(self, value):
        self.value = value


class _FakeClient:
    def __init__(self, balance):
        self.balance = balance
        self.sent = []

    async def get_balance(self, pubkey):
        return _Val(self.balance)

    async def get_latest_blockhash(self):
        from solders.hash import Hash

        class _BH:
            blockhash = Hash.default()

        return _Val(_BH())

    async def send_transaction(self, tx):
        self.sent.append(tx)
        return _Val("5" * 88)

    async def confirm_transaction(self, sig, commitment=None):
        return None

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_anchor_payload_real_path_with_fake_client(monkeypatch):
    kp = Keypair()
    monkeypatch.setattr(web3, "_load_or_generate_keypair", lambda: (kp, False))
    client = _FakeClient(balance=1_000_000)
    canonical = '{"a":1}'
    proof = await anchor_payload(canonical, client=client)
    assert proof.is_simulated is False
    assert proof.data_hash == _sha(canonical)
    assert proof.signer == str(kp.pubkey())
    assert proof.solscan_url.endswith("?cluster=devnet") and proof.tx_signature in proof.solscan_url
    assert proof.canonical_json == canonical
    assert len(client.sent) == 1


@pytest.mark.asyncio
async def test_anchor_payload_low_balance_falls_back_to_simulated(monkeypatch):
    kp = Keypair()
    monkeypatch.setattr(web3, "_load_or_generate_keypair", lambda: (kp, False))
    monkeypatch.setattr(web3.get_settings(), "WEB3_MOCK_FALLBACK", True)
    client = _FakeClient(balance=0)
    proof = await anchor_payload('{"a":1}', client=client)
    assert proof.is_simulated is True and proof.solscan_url == "" and not client.sent


# --- verify_payload ---------------------------------------------------------

def _tx(memo: str, fee_payer: str) -> dict:
    return {
        "slot": 1,
        "meta": {"err": None, "innerInstructions": []},
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


@pytest.mark.asyncio
async def test_verify_payload_valid(monkeypatch, oracle_kp):
    canonical = '{"kind":"bill_check","total":10}'
    monkeypatch.setattr(web3, "_rpc_get_transaction", lambda url, sig: _tx(f"EcoTrust:v1:{_sha(canonical)}", str(oracle_kp.pubkey())))
    res = await verify_payload(canonical, "4" * 88)
    assert res.valid is True and all(res.checks.values())
    assert res.computed_hash == _sha(canonical) and res.canonical_json == canonical


@pytest.mark.asyncio
async def test_verify_payload_mismatch(monkeypatch, oracle_kp):
    monkeypatch.setattr(web3, "_rpc_get_transaction", lambda url, sig: _tx(f"EcoTrust:v1:{_sha('other')}", str(oracle_kp.pubkey())))
    res = await verify_payload('{"a":1}', "4" * 88)
    assert res.valid is False and res.checks["memo_found"] and not res.checks["hash_matches"]


@pytest.mark.asyncio
async def test_verify_payload_never_raises(monkeypatch, oracle_kp):
    monkeypatch.setattr(web3, "_rpc_get_transaction", lambda url, sig: {"transaction": "garbage"})
    res = await verify_payload('{"a":1}', "4" * 88)
    assert res.valid is False


@pytest.mark.asyncio
async def test_verify_anchor_delegates_to_verify_payload(monkeypatch, oracle_kp):
    r = _reading()
    monkeypatch.setattr(web3, "_rpc_get_transaction", lambda url, sig: _tx(f"EcoTrust:v1:{compute_meter_hash(r)}", str(oracle_kp.pubkey())))
    res = await verify_anchor(r, "4" * 88)
    assert res.valid is True and res.canonical_json == canonical_json(r)


# --- audit message ------------------------------------------------------------

def _comparison(**kw) -> ReadingComparison:
    base = dict(
        previous=PreviousReading(value=1200.0, unit="m3", timestamp="2026-11-07T01:00:00Z"),
        consumption=34.5,
        elapsed_hours=24.0,
        daily_rate=34.5,
        typical_daily_rate=30.0,
    )
    base.update(kw)
    return ReadingComparison(**base)


def _limit(status="ok", **kw) -> LimitStatus:
    base = dict(period="month", period_start="2026-11-01T00:00:00Z", limit=100.0, unit="m3",
                used=85.0, percent=85.0, status=status, projected=120.0)
    base.update(kw)
    return LimitStatus(**base)


URL = "https://solscan.io/tx/abc?cluster=devnet"


def test_audit_message_backward_compatible():
    r = _reading()
    assert format_telegram_audit_message(r, URL, "h") == format_telegram_audit_message(
        r, URL, "h", comparison=None, limit_status=None
    )
    msg = format_telegram_audit_message(r, URL, "h")
    assert msg.startswith("<b>ECOTRUST ORACLE - CERTIFICADO DE AUDITORIA ESG</b>")
    assert "Lectura anterior" not in msg and "Limite" not in msg and "ALERTA" not in msg


def test_audit_message_anomaly_comes_first():
    comp = _comparison(consumption=-50.0, anomaly="reading_below_previous", anomaly_message="El contador retrocedio.")
    msg = format_telegram_audit_message(_reading(), URL, "h", comparison=comp)
    lines = msg.split("\n")
    assert lines[0] == "<b>ALERTA: posible alteracion del medidor</b>"
    assert lines[1] == "El contador retrocedio."
    assert "se anclo en Solana como evidencia" in lines[2]
    assert "Lectura anterior:</b> <code>1200 m3</code> (2026-11-07T01:00:00Z)" in msg
    assert "Consumo:</b> <code>-50 m3</code>" in msg
    assert "Ritmo diario:" in msg and "Ritmo diario tipico:" in msg


def test_audit_message_anomaly_simulated_is_honest():
    comp = _comparison(anomaly="abnormal_jump")
    msg = format_telegram_audit_message(_reading(), "", "h", is_simulated=True, comparison=comp)
    assert msg.startswith("<b>ALERTA: posible alteracion del medidor</b>")
    assert "SIMULADO" in msg and "solscan" not in msg.lower()


def test_audit_message_limit_warning_and_exceeded():
    warn = format_telegram_audit_message(_reading(), URL, "h", limit_status=_limit("warning"))
    assert "Limite mensual:</b> <code>85/100 m3 (85.0%)</code>" in warn
    assert "AVISO: se alcanzo el 80% del limite" in warn and "LIMITE SUPERADO" not in warn
    assert "Proyeccion al cierre:</b> <code>120 m3</code>" in warn

    exc = format_telegram_audit_message(
        _reading(), URL, "h", limit_status=_limit("exceeded", period="day", used=130.0, percent=130.0, projected=None)
    )
    assert "Limite diario:" in exc and "LIMITE SUPERADO" in exc and "AVISO" not in exc
    assert "Proyeccion" not in exc


def test_audit_message_escapes_hostile_strings():
    comp = _comparison(
        previous=PreviousReading(value=1.0, unit=HOSTILE, timestamp=HOSTILE),
        anomaly="unit_mismatch",
        anomaly_message=HOSTILE,
    )
    msg = format_telegram_audit_message(
        _reading(unit="<i>x</i>", device_id=HOSTILE), URL, HOSTILE, comparison=comp,
        limit_status=_limit("warning", unit=HOSTILE),
    )
    assert "<script>" not in msg and "&lt;script&gt;" in msg and "<i>x</i>" not in msg


# --- bill message -------------------------------------------------------------

def _bill(**kw) -> BillCheckResult:
    base = dict(
        bill=BillExtraction(
            fields=BillFields(provider="Aguas SA", period_start="2026-10-01", period_end="2026-10-31", currency="USD"),
            disputed=["total_amount", "unit"],
            votes=3,
            total_reads=3,
            model="gemini",
            image_sha256="0" * 64,
        ),
        checks=[
            BillCheckItem(name="consumption_arithmetic", label="Aritmetica del consumo", status="mismatch",
                          detail="120 - 100 = 20, pero se facturaron 35."),
            BillCheckItem(name="continuity", label="Continuidad", status="match", detail="OK continuidad"),
        ],
        verdict="discrepancies",
        overcharge_estimate=12.5,
        currency="USD",
        explanation="Se facturo mas consumo del medido.",
    )
    base.update(kw)
    return BillCheckResult(**base)


def _proof(simulated: bool) -> OracleProof:
    return OracleProof(
        data_hash="ab" * 32,
        tx_signature="SIMULATED-x" if simulated else "5" * 88,
        solscan_url="" if simulated else "https://solscan.io/tx/" + "5" * 88 + "?cluster=devnet",
        memo_payload="EcoTrust:v1:" + "ab" * 32,
        is_simulated=simulated,
    )


def test_bill_message_mismatches_overcharge_real_link():
    msg = format_bill_check_message(_bill(oracle_proof=_proof(False)))
    assert "VERIFICACION DE RECIBO" in msg
    assert "Aguas SA" in msg and "2026-10-01 a 2026-10-31" in msg
    assert "Discrepancias detectadas" in msg
    assert "Aritmetica del consumo:</b> 120 - 100 = 20, pero se facturaron 35." in msg
    assert "OK continuidad" not in msg  # only mismatches are listed
    assert "12.50 USD" in msg and "Campos en disputa:</b> 2" in msg
    assert "ab" * 32 in msg and 'href="https://solscan.io/tx/' in msg and "SIMULADO" not in msg


@pytest.mark.parametrize("proof", [None, _proof(True)])
def test_bill_message_simulated_or_missing_proof_has_no_link(proof):
    msg = format_bill_check_message(_bill(oracle_proof=proof, verdict="consistent", overcharge_estimate=None))
    assert "Consistente" in msg and "SIMULADO - no anclado en Solana" in msg
    assert "solscan" not in msg.lower() and "Sobrecobro" not in msg


def test_bill_message_inconclusive_and_escaping():
    hostile = _bill(verdict="inconclusive", explanation=HOSTILE, currency=HOSTILE)
    hostile.bill.fields.provider = HOSTILE
    hostile.checks[0].label = HOSTILE
    hostile.checks[0].detail = HOSTILE
    msg = format_bill_check_message(hostile)
    assert "No concluyente" in msg and "<script>" not in msg and "&lt;script&gt;" in msg


def test_bill_message_truncation_keeps_hash_and_valid_length():
    checks = [
        BillCheckItem(name=f"c{i}", label=f"Check {i}", status="mismatch", detail="&" * 2000) for i in range(30)
    ]
    msg = format_bill_check_message(_bill(checks=checks, explanation="x" * 5000, oracle_proof=_proof(False)))
    assert len(msg) <= 4096
    assert "ab" * 32 in msg and "Ver prueba en Solscan" in msg and "lineas omitidas" in msg
    # explanation is clipped before escaping
    assert "x" * 601 not in msg


# --- shared delivery ----------------------------------------------------------

def _creds(monkeypatch, token="123:SECRET-TOKEN", chat="111,222"):
    s = notifier.get_settings()
    monkeypatch.setattr(s, "TELEGRAM_BOT_TOKEN", token)
    monkeypatch.setattr(s, "TELEGRAM_CHAT_ID", chat)


@pytest.mark.asyncio
async def test_bill_notification_mock_when_no_credentials(monkeypatch):
    _creds(monkeypatch, token="", chat="")
    monkeypatch.setattr(notifier, "_sync_telegram_send", lambda *a: (_ for _ in ()).throw(AssertionError("no")))
    res = await send_bill_check_notification(_bill())
    assert res.sent is True and res.is_mock is True


@pytest.mark.asyncio
async def test_bill_notification_multi_chat_partial(monkeypatch):
    _creds(monkeypatch)
    sent = []

    def fake(token, cid, text):
        sent.append((cid, text))
        if cid == "222":
            raise RuntimeError(f"https://api.telegram.org/bot{token}/sendMessage failed")
        return {"ok": True, "result": {"message_id": 7}}

    monkeypatch.setattr(notifier, "_sync_telegram_send", fake)
    res = await send_bill_check_notification(_bill())
    assert [c for c, _ in sent] == ["111", "222"]
    assert "VERIFICACION DE RECIBO" in sent[0][1]
    assert res.sent is True and res.recipient == "111" and res.message_id == 7
    assert "SECRET-TOKEN" not in (res.error or "") and "<redacted>" in res.error


@pytest.mark.asyncio
async def test_audit_notification_all_failed_raises_redacted(monkeypatch):
    _creds(monkeypatch)

    def fake(token, cid, text):
        raise RuntimeError(f"boom bot{token}")

    monkeypatch.setattr(notifier, "_sync_telegram_send", fake)
    with pytest.raises(NotificationError) as ei:
        await send_audit_notification(_reading(), URL, "h", comparison=_comparison(), limit_status=_limit("exceeded"))
    assert "SECRET-TOKEN" not in str(ei.value)


@pytest.mark.asyncio
async def test_audit_notification_passes_new_blocks(monkeypatch):
    _creds(monkeypatch, chat="111")
    texts = []
    monkeypatch.setattr(notifier, "_sync_telegram_send",
                        lambda token, cid, text: texts.append(text) or {"ok": True, "result": {"message_id": 1}})
    comp = _comparison(anomaly="abnormal_jump", anomaly_message="Salto anormal.")
    res = await send_audit_notification(_reading(), URL, "h", comparison=comp, limit_status=_limit("warning"))
    assert res.sent and not res.is_mock
    assert texts[0].startswith("<b>ALERTA: posible alteracion del medidor</b>")
    assert "AVISO: se alcanzo el 80% del limite" in texts[0]
