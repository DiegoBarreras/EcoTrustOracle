"""
Keep the test suite offline: blank out real credentials from .env before the app loads its settings.
Environment variables take precedence over .env, so tests never call the vision API,
spend Devnet SOL or message real Telegram chats.
"""

import os

for _var in ("VISION_API_KEY", "GEMINI_API_KEY", "SOLANA_PRIVATE_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
    os.environ[_var] = ""
