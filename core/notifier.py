"""
EcoTrust Oracle - Telegram Notifier Module (Developer 3)
Formats verifiable ESG audit certificates and delivers real-time compliance
notifications to stakeholders via the Telegram Bot API using requests.
"""

import asyncio
import html
import logging
from typing import Dict, Any, Union, Optional
import requests

from core.config import get_settings
from core.schemas import MeterReading, NotificationResult

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


def format_telegram_audit_message(
    reading: Union[MeterReading, Dict[str, Any]],
    solscan_url: str,
    data_hash: Optional[str] = None,
    is_simulated: bool = False,
    consumption: Optional[float] = None,
    compliance: Optional[Any] = None,
) -> str:
    """
    Constructs the ESG compliance certificate message formatted in HTML for Telegram.
    Every interpolated value is HTML-escaped. Simulated proofs carry no explorer link
    and no on-chain claim.
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

    if compliance is not None and getattr(compliance, "is_breach", False):
        title = "🚨 <b>ECOTRUST ORACLE - ALERTA DE INCUMPLIMIENTO ESG</b>"
        comp_section = (
            "--------------------------------\n"
            f"🚨 <b>ESTADO: UMBRAL MENSUAL EXCEDIDO (+{compliance.excess_percentage}%)</b>\n"
            f"⚡ <b>Consumo evaluado:</b> <code>{e(consumption if consumption is not None else val)} {e(unit)}</code>\n"
            f"🎯 <b>Umbral mensual esperado:</b> <code>{e(compliance.threshold)} {e(unit)}</code>\n"
            "⚠️ <i>Infracción de sobreconsumo auditada y anclada en Solana.</i>\n"
        )
    elif compliance is not None and not getattr(compliance, "is_breach", False):
        title = "🌿 <b>ECOTRUST ORACLE - CERTIFICADO DE AUDITORIA ESG</b>"
        usage_pct = round((consumption / compliance.threshold) * 100, 1) if consumption is not None and compliance.threshold > 0 else 0
        comp_section = (
            "--------------------------------\n"
            f"🟢 <b>ESTADO ESG: CUMPLIMIENTO CONFORME ({usage_pct}%)</b>\n"
            f"⚡ <b>Consumo evaluado:</b> <code>{e(consumption if consumption is not None else val)} {e(unit)}</code>\n"
            f"🎯 <b>Umbral mensual esperado:</b> <code>{e(compliance.threshold)} {e(unit)}</code>\n"
            "✅ <i>Consumo dentro del límite corporativo permitido.</i>\n"
        )
    elif consumption is not None:
        title = "🌿 <b>ECOTRUST ORACLE - CERTIFICADO DE AUDITORIA ESG</b>"
        comp_section = (
            "--------------------------------\n"
            f"⚡ <b>Consumo del periodo:</b> <code>{e(consumption)} {e(unit)}</code>\n"
        )
    else:
        title = "🌿 <b>ECOTRUST ORACLE - CERTIFICADO DE AUDITORIA ESG</b>"
        comp_section = ""

    message = (
        f"{title}\n"
        "--------------------------------\n"
        f"<b>Lectura:</b> <code>{e(val)} {e(unit)}</code>\n"
        f"<b>Fuente:</b> <code>{e(source_label)}</code>\n"
        f"{asset_line}"
        f"<b>Confianza:</b> <code>{e(conf_pct)}</code>\n"
        f"<b>Fecha (UTC):</b> <code>{e(timestamp)}</code>\n"
        f"{hash_line}"
        f"{comp_section}"
        "--------------------------------\n"
        f"{anchor_block}"
    )
    return message


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

    Returns:
        NotificationResult: Delivery status and Telegram message ID.
    """
    settings = get_settings()
    target_chat = chat_id or settings.TELEGRAM_CHAT_ID
    bot_token = settings.TELEGRAM_BOT_TOKEN
    message_text = format_telegram_audit_message(reading, solscan_url, data_hash, is_simulated=is_simulated, consumption=consumption, compliance=compliance)

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
