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

    try:
        # Offload synchronous requests call to asyncio threadpool
        res = await asyncio.to_thread(_sync_telegram_send, bot_token, str(target_chat), message_text)
        result_payload = res.get("result", {})
        msg_id = result_payload.get("message_id")

        logger.info(f"✅ [Notifier] Telegram message delivered to {target_chat} (Message ID: {msg_id})")
        return NotificationResult(
            sent=True,
            channel="telegram",
            recipient=str(target_chat),
            message_id=msg_id,
            is_mock=False,
            error=None,
        )

    except Exception as exc:
        logger.error(f"❌ [Notifier] Telegram notification dispatch failed: {exc}", exc_info=True)
        if settings.NOTIFIER_MOCK_FALLBACK:
            return NotificationResult(
                sent=True,
                channel="telegram",
                recipient=str(target_chat),
                message_id=None,
                is_mock=True,
                error=str(exc),
            )
        raise NotificationError(f"Failed to dispatch Telegram message: {exc}") from exc
