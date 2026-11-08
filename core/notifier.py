"""
EcoTrust Oracle - Telegram Notifier Module (Developer 3)
Formats verifiable ESG audit certificates and delivers real-time compliance
notifications to stakeholders via the Telegram Bot API using requests.
"""

import asyncio
import html
import logging
import re
from typing import Dict, Any, List, Union, Optional
import requests

from core.config import get_settings
from core.schemas import (
    BillCheckResult,
    LimitStatus,
    MeterReading,
    NotificationResult,
    ReadingComparison,
)

logger = logging.getLogger("ecotrust.notifier")


class NotificationError(Exception):
    """Raised when Telegram message delivery fails."""
    pass


def _redact(text: Any, token: Optional[str] = None) -> str:
    """Removes the bot token from any text (requests exceptions embed the /bot<TOKEN>/ URL)."""
    out = str(text)
    token = token if token is not None else get_settings().TELEGRAM_BOT_TOKEN
    if token:
        out = out.replace(token, "<redacted>")
    return out


TELEGRAM_MAX_CHARS = 4096
EXPLANATION_MAX_CHARS = 600
DETAIL_MAX_CHARS = 400

_PERIOD_LABELS = {"day": "diario", "week": "semanal", "month": "mensual"}
_VERDICT_LABELS = {
    "consistent": "Consistente",
    "discrepancies": "Discrepancias detectadas",
    "inconclusive": "No concluyente",
}
_ANOMALY_DEFAULTS = {
    "reading_below_previous": "La lectura es menor que la anterior: el contador retrocedio.",
    "unit_mismatch": "La unidad no coincide con la de la lectura anterior.",
    "abnormal_jump": "El consumo es anormalmente alto respecto al historial del medidor.",
}


def _e(v: Any) -> str:
    return html.escape(str(v), quote=False)


def _clip(text: Any, limit: int) -> str:
    """Truncates plain text (before escaping, so no HTML entity is ever cut)."""
    s = str(text)
    return s if len(s) <= limit else s[: max(0, limit - 3)].rstrip() + "..."


def _num(v: Any) -> str:
    """Compact number: up to 4 decimals, no trailing zeros."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    out = f"{f:.4f}".rstrip("0").rstrip(".")
    return "0" if out in ("-0", "") else out


def _fit_lines(head: List[str], body: List[str], tail: List[str], limit: int = TELEGRAM_MAX_CHARS) -> str:
    """
    Joins self-contained HTML lines (every tag opened in a line is closed in it), dropping
    body lines from the end when the message would exceed `limit`. Head and tail are kept.
    """
    def join(lines: List[str]) -> str:
        return "\n".join(lines)

    full = join(head + body + tail)
    if len(full) <= limit:
        return full
    kept = list(body)
    while kept:
        kept.pop()
        omitted = len(body) - len(kept)
        candidate = join(head + kept + [f"<i>... ({omitted} lineas omitidas por longitud)</i>"] + tail)
        if len(candidate) <= limit:
            return candidate
    return _truncate_html_lines(join(head + tail), limit)


def _truncate_html_lines(message: str, limit: int = TELEGRAM_MAX_CHARS) -> str:
    """Last-resort guard: cuts at a line boundary so no HTML tag is left open."""
    if len(message) <= limit:
        return message
    suffix = "\n..."
    cut = message.rfind("\n", 0, limit - len(suffix))
    if cut <= 0:
        # Single huge line: drop markup entirely and send escaped plain text.
        plain = html.unescape(re.sub(r"<[^>]+>", "", message))
        return _e(_clip(plain, limit // 6))  # escaping can grow each char up to 5x ("&amp;")
    return message[:cut] + suffix


def _comparison_lines(comparison: ReadingComparison) -> List[str]:
    prev = comparison.previous
    unit = prev.unit
    lines = [
        f"<b>Lectura anterior:</b> <code>{_e(_num(prev.value))} {_e(unit)}</code> ({_e(prev.timestamp)})",
        f"<b>Consumo:</b> <code>{_e(_num(comparison.consumption))} {_e(unit)}</code>",
    ]
    if comparison.daily_rate is not None:
        lines.append(f"<b>Ritmo diario:</b> <code>{_e(_num(comparison.daily_rate))} {_e(unit)}/dia</code>")
    if comparison.typical_daily_rate is not None:
        lines.append(
            f"<b>Ritmo diario tipico:</b> <code>{_e(_num(comparison.typical_daily_rate))} {_e(unit)}/dia</code>"
        )
    return lines


def _limit_lines(limit_status: LimitStatus) -> List[str]:
    period = _PERIOD_LABELS.get(limit_status.period, str(limit_status.period))
    unit = limit_status.unit
    lines = [
        f"<b>Limite {_e(period)}:</b> <code>{_e(_num(limit_status.used))}/{_e(_num(limit_status.limit))} "
        f"{_e(unit)} ({_e(f'{float(limit_status.percent):.1f}')}%)</code>"
    ]
    if limit_status.status == "exceeded":
        lines.append("<b>LIMITE SUPERADO</b>")
    elif limit_status.status == "warning":
        lines.append("<b>AVISO: se alcanzo el 80% del limite</b>")
    if limit_status.projected is not None:
        lines.append(f"<b>Proyeccion al cierre:</b> <code>{_e(_num(limit_status.projected))} {_e(unit)}</code>")
    return lines


def format_telegram_audit_message(
    reading: Union[MeterReading, Dict[str, Any]],
    solscan_url: str,
    data_hash: Optional[str] = None,
    is_simulated: bool = False,
    *,
    comparison: Optional[ReadingComparison] = None,
    limit_status: Optional[LimitStatus] = None,
    consumption: Optional[float] = None,
    compliance: Optional[Any] = None,
) -> str:
    """
    Constructs the ESG compliance certificate message formatted in HTML for Telegram.
    Every interpolated value is HTML-escaped. Simulated proofs carry no explorer link
    and no on-chain claim. With no comparison/limit the output is unchanged.
    """
    if isinstance(reading, MeterReading):
        val = reading.value
        unit = reading.unit
        conf = reading.confidence
        timestamp = reading.timestamp
        source = reading.source
        device_id = reading.device_id
    else:
        val = reading.get("value", "N/A")
        unit = reading.get("unit", "")
        conf = reading.get("confidence", 0.0)
        timestamp = reading.get("timestamp", "N/A")
        source = reading.get("source", "ai_vision")
        device_id = reading.get("device_id")

    def e(v: Any) -> str:
        return html.escape(str(v), quote=False)

    try:
        conf_pct = f"{float(conf) * 100:.1f}%"
    except (TypeError, ValueError):
        conf_pct = "N/A"
    source_label = "Sensor IoT directo" if source == "iot_sensor" else "Gemini AI Vision"
    asset_line = f"<b>Activo:</b> <code>{e(device_id)}</code>\n" if device_id else ""
    hash_line = f"<b>SHA-256:</b> <code>{e(data_hash)}</code>\n" if data_hash else ""

    if is_simulated or not solscan_url:
        anchor_block = (
            "<b>Anclaje en Solana:</b> SIMULADO - no anclado en Solana\n"
            "<i>Esta lectura no tiene prueba en la cadena.</i>"
        )
    else:
        anchor_block = (
            "<b>Anclaje en Solana Devnet:</b>\n"
            f"<a href=\"{html.escape(solscan_url, quote=True)}\"><b>Ver prueba en Solscan</b></a>\n\n"
            "<i>Estado: lectura anclada en Solana; verificable con el hash SHA-256.</i>"
        )

    alert_block = ""
    if comparison is not None and comparison.anomaly:
        anomaly_text = comparison.anomaly_message or _ANOMALY_DEFAULTS.get(comparison.anomaly, str(comparison.anomaly))
        anchored = not (is_simulated or not solscan_url)
        evidence = (
            "La lectura se registro y se anclo en Solana como evidencia."
            if anchored
            else "La lectura se registro como evidencia; el anclaje fue SIMULADO (no anclado en Solana)."
        )
        alert_block = (
            "<b>ALERTA: posible alteracion del medidor</b>\n"
            f"{e(_clip(anomaly_text, DETAIL_MAX_CHARS))}\n"
            f"<i>{e(evidence)}</i>\n\n"
        )

    # ESG monthly-threshold compliance (also tagged on-chain in the memo as :EXCEEDED / :COMPLIANT).
    title = "<b>ECOTRUST ORACLE - CERTIFICADO DE AUDITORIA ESG</b>"
    evaluated = consumption if consumption is not None else val
    comp_section = ""
    if compliance is not None and getattr(compliance, "is_breach", False):
        title = "<b>ECOTRUST ORACLE - ALERTA DE INCUMPLIMIENTO ESG</b>"
        comp_section = (
            "--------------------------------\n"
            f"<b>ESTADO: UMBRAL MENSUAL EXCEDIDO (+{e(compliance.excess_percentage)}%)</b>\n"
            f"<b>Consumo evaluado:</b> <code>{e(evaluated)} {e(unit)}</code>\n"
            f"<b>Umbral mensual esperado:</b> <code>{e(compliance.threshold)} {e(unit)}</code>\n"
            "<i>Sobreconsumo auditado y registrado en el memo de Solana.</i>\n"
        )
    elif compliance is not None:
        usage_pct = round((consumption / compliance.threshold) * 100, 1) if consumption is not None and compliance.threshold > 0 else 0
        comp_section = (
            "--------------------------------\n"
            f"<b>ESTADO ESG: CUMPLIMIENTO CONFORME ({e(usage_pct)}%)</b>\n"
            f"<b>Consumo evaluado:</b> <code>{e(evaluated)} {e(unit)}</code>\n"
            f"<b>Umbral mensual esperado:</b> <code>{e(compliance.threshold)} {e(unit)}</code>\n"
            "<i>Consumo dentro del limite corporativo permitido.</i>\n"
        )
    elif consumption is not None and comparison is None:
        comp_section = (
            "--------------------------------\n"
            f"<b>Consumo del periodo:</b> <code>{e(consumption)} {e(unit)}</code>\n"
        )

    extra_lines: List[str] = []
    if comparison is not None:
        extra_lines += _comparison_lines(comparison)
    if limit_status is not None:
        extra_lines += _limit_lines(limit_status)
    extra_block = ("--------------------------------\n" + "\n".join(extra_lines) + "\n") if extra_lines else ""

    message = (
        f"{alert_block}"
        f"{title}\n"
        "--------------------------------\n"
        f"<b>Lectura:</b> <code>{e(val)} {e(unit)}</code>\n"
        f"<b>Fuente:</b> <code>{e(source_label)}</code>\n"
        f"{asset_line}"
        f"<b>Confianza:</b> <code>{e(conf_pct)}</code>\n"
        f"<b>Fecha (UTC):</b> <code>{e(timestamp)}</code>\n"
        f"{hash_line}"
        f"{extra_block}"
        f"{comp_section}"
        "--------------------------------\n"
        f"{anchor_block}"
    )
    return _truncate_html_lines(message)


def format_bill_check_message(result: BillCheckResult) -> str:
    """HTML Telegram message for a bill check. Every value escaped; fits in 4096 chars."""
    fields = result.bill.fields
    proof = result.oracle_proof
    verdict = _VERDICT_LABELS.get(result.verdict, str(result.verdict))

    head = [
        "<b>ECOTRUST ORACLE - VERIFICACION DE RECIBO</b>",
        "--------------------------------",
        f"<b>Proveedor:</b> <code>{_e(_clip(fields.provider or 'N/D', 120))}</code>",
        f"<b>Periodo:</b> <code>{_e(_clip(fields.period_start or 'N/D', 40))} a "
        f"{_e(_clip(fields.period_end or 'N/D', 40))}</code>",
        f"<b>Veredicto:</b> <b>{_e(verdict)}</b>",
    ]
    currency = result.currency or fields.currency
    if result.overcharge_estimate is not None:
        amount = f"{float(result.overcharge_estimate):.2f}"
        cur = f" {_clip(currency, 16)}" if currency else ""
        head.append(f"<b>Sobrecobro estimado:</b> <code>{_e(amount)}{_e(cur)}</code>")
    if result.bill.disputed:
        head.append(
            f"<b>Campos en disputa:</b> {len(result.bill.disputed)} "
            "(las lecturas independientes no coincidieron)"
        )

    body: List[str] = []
    mismatches = [c for c in result.checks if c.status == "mismatch"]
    if mismatches:
        body.append("<b>Discrepancias:</b>")
        for c in mismatches:
            body.append(f"- <b>{_e(_clip(c.label, 120))}:</b> {_e(_clip(c.detail, DETAIL_MAX_CHARS))}")
    if result.explanation:
        body.append(f"<b>Explicacion:</b> {_e(_clip(result.explanation, EXPLANATION_MAX_CHARS))}")

    tail = ["--------------------------------"]
    if proof is not None:
        tail.append(f"<b>SHA-256:</b> <code>{_e(proof.data_hash)}</code>")
    if proof is not None and not proof.is_simulated and proof.solscan_url:
        tail.append(
            f"<a href=\"{html.escape(proof.solscan_url, quote=True)}\"><b>Ver prueba en Solscan</b></a>"
        )
        tail.append("<i>Estado: verificacion anclada en Solana; verificable con el hash SHA-256.</i>")
    else:
        tail.append("<b>Anclaje en Solana:</b> SIMULADO - no anclado en Solana")

    return _fit_lines(head, body, tail)


def _sync_telegram_send(
    token: str,
    chat_id: str,
    message_text: str,
) -> Dict[str, Any]:
    """
    Synchronous worker executing the requests.post call against the Telegram Bot API.
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    response = requests.post(url, json=payload, timeout=10.0)
    data = response.json()
    if not response.ok or not data.get("ok"):
        desc = data.get("description", "Unknown Telegram API error")
        raise NotificationError(f"Telegram API responded with error: {desc} (status code: {response.status_code})")
    return data


async def send_audit_notification(
    reading: Union[MeterReading, Dict[str, Any]],
    solscan_url: str,
    data_hash: Optional[str] = None,
    chat_id: Optional[str] = None,
    *,
    is_simulated: bool = False,
    comparison: Optional[ReadingComparison] = None,
    limit_status: Optional[LimitStatus] = None,
    consumption: Optional[float] = None,
    compliance: Optional[Any] = None,
) -> NotificationResult:
    """
    Asynchronously delivers the ESG audit notification via Telegram.

    Args:
        reading: The verified meter reading.
        solscan_url: Blockchain explorer URL of the anchored memo.
        data_hash: Optional SHA-256 hash string for display.
        chat_id: Optional override for Telegram recipient chat ID.
        is_simulated: True when the proof was never anchored (no Solscan link is shown).
        comparison: Optional comparison with the previous reading (anomalies go first).
        limit_status: Optional consumption limit status for the period.

    Returns:
        NotificationResult: Delivery status and Telegram message ID.
    """
    message_text = format_telegram_audit_message(
        reading,
        solscan_url,
        data_hash,
        is_simulated=is_simulated,
        comparison=comparison,
        limit_status=limit_status,
        consumption=consumption,
        compliance=compliance,
    )
    return await _deliver(message_text, chat_id)


async def send_bill_check_notification(
    result: BillCheckResult,
    chat_id: Optional[str] = None,
) -> NotificationResult:
    """Delivers the bill check summary (verdict, mismatches, hash, Solscan link) via Telegram."""
    return await _deliver(format_bill_check_message(result), chat_id)


async def _deliver(message_text: str, chat_id: Optional[str] = None) -> NotificationResult:
    """
    Shared Telegram delivery: comma-separated chat IDs, partial delivery = sent with error,
    all recipients failed with credentials configured -> NotificationError (token redacted),
    mock result only when credentials are missing.
    """
    settings = get_settings()
    target_chat = chat_id or settings.TELEGRAM_CHAT_ID
    bot_token = settings.TELEGRAM_BOT_TOKEN
    message_text = _truncate_html_lines(message_text)

    # Check for missing credentials -> fallback to mock log
    if not bot_token or not target_chat:
        if settings.NOTIFIER_MOCK_FALLBACK:
            logger.warning(
                "⚠️ [Notifier] TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing. Utilizing MOCK notification delivery."
            )
            logger.info(f"📨 [MOCK Telegram Dispatch to {target_chat or 'Local Console'}]:\n{message_text}")
            return NotificationResult(
                sent=True,
                channel="telegram",
                recipient=target_chat or "MOCK_CONSOLE",
                message_id="mock-msg-001",
                is_mock=True,
                error=None,
            )
        raise NotificationError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not configured")

    # TELEGRAM_CHAT_ID (or the override) may hold several comma-separated chat IDs.
    chat_ids = [c.strip() for c in str(target_chat).split(",") if c.strip()]
    delivered: Dict[str, Any] = {}
    failures: Dict[str, str] = {}
    for cid in chat_ids:
        try:
            # Offload synchronous requests call to asyncio threadpool
            res = await asyncio.to_thread(_sync_telegram_send, bot_token, cid, message_text)
            delivered[cid] = res.get("result", {}).get("message_id")
            logger.info(f"✅ [Notifier] Telegram message delivered to {cid} (Message ID: {delivered[cid]})")
        except Exception as exc:
            safe = _redact(exc, bot_token)
            logger.error(f"[Notifier] Telegram dispatch to {cid} failed: {type(exc).__name__}: {safe}")
            failures[cid] = safe

    error = "; ".join(f"{cid}: {err}" for cid, err in failures.items()) or None
    if delivered:
        # Partial delivery still counts as sent; failed recipients are reported in `error`.
        return NotificationResult(
            sent=True,
            channel="telegram",
            recipient=",".join(delivered),
            message_id=next(iter(delivered.values())) if len(delivered) == 1 else ",".join(str(m) for m in delivered.values()),
            is_mock=False,
            error=error,
        )

    # Credentials are configured but nobody received it: a real failure, never a mock.
    error = error or "no valid chat IDs"
    raise NotificationError(_redact(f"Failed to dispatch Telegram message: {error}", bot_token))


async def poll_telegram_commands(stop_event: asyncio.Event) -> None:
    """
    Background worker that listens for Telegram commands like /start, /status, /help
    and replies interactively to users, acknowledging their chat ID for compliance alerts.
    """
    settings = get_settings()
    bot_token = settings.TELEGRAM_BOT_TOKEN
    if not bot_token:
        logger.info("ℹ️ [Telegram Poller] No TELEGRAM_BOT_TOKEN provided; poller disabled.")
        return

    offset: Optional[int] = None
    logger.info("🤖 [Telegram Poller] Started interactive Telegram command listener.")

    while not stop_event.is_set():
        try:
            url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
            params: Dict[str, Any] = {"timeout": 3}
            if offset is not None:
                params["offset"] = offset

            resp = await asyncio.to_thread(requests.get, url, params=params, timeout=10.0)
            data = resp.json()

            if not data.get("ok"):
                await asyncio.sleep(2.0)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                msg = update.get("message")
                if not msg:
                    continue

                chat_id = msg.get("chat", {}).get("id")
                text = (msg.get("text") or "").strip()
                user_name = html.escape(str(msg.get("from", {}).get("first_name", "Auditor")), quote=False)
                safe_chat = html.escape(str(chat_id), quote=False)

                if text.startswith("/start"):
                    reply = (
                        "<b>ECOTRUST ORACLE - BOT DE CUMPLIMIENTO ESG</b>\n"
                        "--------------------------------\n"
                        f"Hola <b>{user_name}</b>.\n\n"
                        f"<b>Tu Chat ID:</b> <code>{safe_chat}</code>\n\n"
                        "Para recibir certificados de auditoria, este Chat ID debe agregarse a "
                        "TELEGRAM_CHAT_ID en la configuracion del oraculo. Hasta entonces no recibiras certificados.\n\n"
                        "<b>Comandos:</b>\n"
                        "/status - Estado del oraculo y Solana\n"
                        "/help - Guia rapida de uso"
                    )
                    await asyncio.to_thread(_sync_telegram_send, bot_token, str(chat_id), reply)
                    logger.info(f"[Telegram Poller] Answered /start from {user_name} ({chat_id})")

                elif text.startswith("/status"):
                    reply = (
                        "<b>EcoTrust Oracle - Estado Operativo</b>\n"
                        "--------------------------------\n"
                        "<b>Blockchain:</b> Solana Devnet\n"
                        f"<b>Memo Program:</b> <code>{html.escape(settings.SOLANA_MEMO_PROGRAM_ID, quote=False)}</code>\n"
                        "<b>AI Vision:</b> Multi-Provider (Gemini / Claude / DeepSeek)\n"
                        "<b>API Gateway:</b> Operacional (FastAPI)\n"
                        "<b>Dashboard:</b> http://localhost:3000"
                    )
                    await asyncio.to_thread(_sync_telegram_send, bot_token, str(chat_id), reply)
                    logger.info(f"[Telegram Poller] Answered /status from {chat_id}")

                elif text.startswith("/help"):
                    reply = (
                        "<b>EcoTrust Oracle - Ayuda</b>\n\n"
                        "1. Abre el dashboard web en <code>http://localhost:3000</code>.\n"
                        "2. Conecta tu billetera de Solana (Phantom / Solflare).\n"
                        "3. Sube la foto de un medidor industrial o introduce datos de sensor IoT.\n"
                        "4. Haz clic en Auditar. Si tu Chat ID esta en TELEGRAM_CHAT_ID, "
                        "recibiras aqui el certificado con el hash y el enlace de Solscan."
                    )
                    await asyncio.to_thread(_sync_telegram_send, bot_token, str(chat_id), reply)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"[Telegram Poller] Warning during update poll: {type(exc).__name__}: {_redact(exc, bot_token)}")
            await asyncio.sleep(2.0)

        await asyncio.sleep(0.5)

    logger.info("🛑 [Telegram Poller] Stopped Telegram command listener.")
