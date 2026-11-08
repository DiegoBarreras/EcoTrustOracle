"""
EcoTrust Oracle - Configuration Management
Loads environment variables using pydantic-settings and python-dotenv.
Provides sensible defaults and fallback toggles for hackathon development.
"""

from functools import lru_cache
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment variable overrides."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server configuration
    APP_NAME: str = "EcoTrust Oracle - B2B Physical Oracle"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: str = Field(default="development", description="development | staging | production")
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # AI Vision (Google Gemini)
    GEMINI_API_KEY: Optional[str] = Field(
        default=None,
        description="Google Generative AI API Key for Gemini 1.5 Flash Vision",
    )
    GEMINI_MODEL: str = "gemini-1.5-flash"
    VISION_MOCK_FALLBACK: bool = Field(
        default=True,
        description="Enable high-fidelity mock data if Gemini API fails or key is missing",
    )

    # Web3 / Solana Configuration
    SOLANA_RPC_URL: str = Field(
        default="https://api.devnet.solana.com",
        description="Solana Devnet RPC endpoint",
    )
    SOLANA_PRIVATE_KEY: Optional[str] = Field(
        default=None,
        description="Solana Keypair secret key (base58 encoded or JSON array). If absent, simulated anchoring is used.",
    )
    SOLANA_COMMITMENT: str = "confirmed"
    SOLANA_MEMO_PROGRAM_ID: str = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
    SOLSCAN_BASE_URL: str = "https://solscan.io/tx"
    WEB3_MOCK_FALLBACK: bool = Field(
        default=True,
        description="Enable simulated Devnet transaction anchoring if wallet has no SOL or RPC is unreachable",
    )

    # Notifications (Telegram Bot API)
    TELEGRAM_BOT_TOKEN: Optional[str] = Field(
        default=None,
        description="Telegram Bot API token from @BotFather",
    )
    TELEGRAM_CHAT_ID: Optional[str] = Field(
        default=None,
        description="Telegram Default Chat / Channel ID to receive ESG audit alerts",
    )
    NOTIFIER_MOCK_FALLBACK: bool = Field(
        default=True,
        description="Enable mock console logging if Telegram credentials are not set",
    )


@lru_cache()
def get_settings() -> Settings:
    """Singleton getter for application settings."""
    return Settings()
