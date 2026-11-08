"""
EcoTrust Oracle - Telegram Notifier Module (Developer 3)
Formats verifiable ESG audit certificates and delivers real-time compliance
notifications to stakeholders via the Telegram Bot API using requests.
"""

import asyncio
import logging
from typing import Dict, Any, Union, Optional
import requests

from core.config import get_settings
from core.schemas import MeterReading, NotificationResult

logger = logging.getLogger("ecotrust.notifier")


class NotificationError(Exception):
    """Raised when Telegram message delivery fails."""
    pass


def format_telegram_audit_message(
    reading: Union[MeterReading, Dict[str, Any]],
    solscan_url: str,
    data_hash: Optional[str] = None,
) -> str:
    """
    Constructs a high-impact, professional ESG compliance certificate message
    formatted in HTML for Telegram delivery.
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

    conf_pct = f"{float(conf) * 100:.1f}%"
    hash_short = f"{data_hash[:16]}...{data_hash[-8:]}" if data_hash else "Verified"
    source_label = "🔌 Direct IoT Sensor" if source == "iot_sensor" else "📸 Gemini AI Vision"
    asset_line = f"🏷 <b>Asset Tag:</b> <code>{device_id}</code>\n" if device_id else ""

    message = (
        "🌿 <b>ECOTRUST ORACLE — ESG AUDIT CERTIFICATE</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 <b>Meter Reading:</b> <code>{val} {unit}</code>\n"
        f"📡 <b>Source:</b> <code>{source_label}</code>\n"
        f"{asset_line}"
        f"🎯 <b>Accuracy/Confidence:</b> <code>{conf_pct}</code>\n"
        f"⏱ <b>Timestamp (UTC):</b> <code>{timestamp}</code>\n"
        f"🔒 <b>SHA-256 Digest:</b> <code>{hash_short}</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⛓ <b>Solana Devnet Anchor:</b>\n"
        f"👉 <a href=\"{solscan_url}\"><b>View Proof on Solscan</b></a>\n\n"
        "✅ <i>Status: Tamper-proof physical audit verified on Solana.</i>\n"
        "🏢 <i>B2B Corporate Compliance & ESG Reporting</i>"
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
) -> NotificationResult:
    """
    Asynchronously delivers the ESG audit notification via Telegram.

    Args:
        reading: The verified meter reading.
        solscan_url: Blockchain explorer URL of the anchored memo.
        data_hash: Optional SHA-256 hash string for display.
        chat_id: Optional override for Telegram recipient chat ID.

    Returns:
        NotificationResult: Delivery status and Telegram message ID.
    """
    settings = get_settings()
    target_chat = chat_id or settings.TELEGRAM_CHAT_ID
    bot_token = settings.TELEGRAM_BOT_TOKEN
    message_text = format_telegram_audit_message(reading, solscan_url, data_hash)

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
            logger.error(f"❌ [Notifier] Telegram dispatch to {cid} failed: {exc}", exc_info=True)
            failures[cid] = str(exc)

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

    error = error or "no valid chat IDs"
    if settings.NOTIFIER_MOCK_FALLBACK:
        return NotificationResult(
            sent=True,
            channel="telegram",
            recipient=str(target_chat),
            message_id=None,
            is_mock=True,
            error=error,
        )
    raise NotificationError(f"Failed to dispatch Telegram message: {error}")


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
                user_name = msg.get("from", {}).get("first_name", "Auditor")

                if text.startswith("/start"):
                    reply = (
                        f"🌿 <b>ECOTRUST ORACLE — ESG COMPLIANCE BOT</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"¡Hola <b>{user_name}</b>! 👋\n\n"
                        f"Tu cuenta ha sido vinculada con éxito al Oráculo Físico de EcoTrust.\n"
                        f"🆔 <b>Tu Chat ID:</b> <code>{chat_id}</code>\n\n"
                        f"✅ A partir de ahora recibirás aquí los certificados de auditoría física "
                        f"anclados de forma inmutable en <b>Solana Devnet</b> cada vez que se registre un medidor o sensor.\n\n"
                        f"<b>Comandos:</b>\n"
                        f"• /status — Verificar estado del oráculo y Solana\n"
                        f"• /help — Guía rápida de uso"
                    )
                    await asyncio.to_thread(_sync_telegram_send, bot_token, str(chat_id), reply)
                    logger.info(f"✅ [Telegram Poller] Answered /start from {user_name} ({chat_id})")

                elif text.startswith("/status"):
                    reply = (
                        f"🌿 <b>EcoTrust Oracle — Estado Operativo</b>\n"
                        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        f"⚡ <b>Blockchain:</b> Solana Devnet\n"
                        f"🔒 <b>Memo Program:</b> <code>MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr</code>\n"
                        f"🤖 <b>AI Vision:</b> Multi-Provider (Gemini / Claude / DeepSeek)\n"
                        f"🟢 <b>API Gateway:</b> Operacional (FastAPI)\n"
                        f"🌐 <b>Dashboard:</b> http://localhost:3000"
                    )
                    await asyncio.to_thread(_sync_telegram_send, bot_token, str(chat_id), reply)
                    logger.info(f"✅ [Telegram Poller] Answered /status from {chat_id}")

                elif text.startswith("/help"):
                    reply = (
                        f"ℹ️ <b>EcoTrust Oracle — Ayuda</b>\n\n"
                        f"1. Abre el dashboard web en <code>http://localhost:3000</code>.\n"
                        f"2. Conecta tu billetera de Solana (Phantom / Solflare).\n"
                        f"3. Sube la foto de un medidor industrial o introduce datos de sensor IoT.\n"
                        f"4. Haz clic en 'Auditar'. Recibirás el certificado con link de Solscan aquí mismo en segundos."
                    )
                    await asyncio.to_thread(_sync_telegram_send, bot_token, str(chat_id), reply)

        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning(f"⚠️ [Telegram Poller] Warning during update poll: {exc}")
            await asyncio.sleep(2.0)

        await asyncio.sleep(0.5)

    logger.info("🛑 [Telegram Poller] Stopped Telegram command listener.")
