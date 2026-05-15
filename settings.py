"""
Application configuration using Pydantic Settings.
All settings loaded from environment variables / .env file.
"""

import os
import secrets
from functools import lru_cache
from typing import List, Optional

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # ─── Bot Configuration ────────────────────────────────────────────────────
    BOT_TOKEN: str
    BOT_NAME: str = "Media Downloader Bot"
    VERSION: str = "2.0.0"
    ENVIRONMENT: str = "production"

    # ─── Webhook Configuration (Render.com) ───────────────────────────────────
    USE_WEBHOOK: bool = True
    WEBHOOK_URL: str = ""          # e.g. https://your-app.onrender.com
    WEBHOOK_PATH: str = "/webhook"
    WEBHOOK_SECRET: str = secrets.token_urlsafe(32)
    HOST: str = "0.0.0.0"
    PORT: int = int(os.getenv("PORT", 10000))

    # ─── Database Configuration ───────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/bot.db"
    # For PostgreSQL: postgresql+asyncpg://user:pass@host:5432/dbname

    # ─── Redis Configuration ──────────────────────────────────────────────────
    REDIS_URL: Optional[str] = None
    CACHE_TTL: int = 3600  # seconds

    # ─── Admin Configuration ──────────────────────────────────────────────────
    ADMIN_IDS: List[int] = []

    @field_validator("ADMIN_IDS", mode="before")
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v

    # ─── Download Configuration ───────────────────────────────────────────────
    DOWNLOAD_DIR: str = "./downloads"
    MAX_FILE_SIZE_MB: int = 50       # Telegram limit for bots
    MAX_CONCURRENT_DOWNLOADS: int = 5
    DOWNLOAD_TIMEOUT: int = 300      # seconds

    # ─── Rate Limiting ────────────────────────────────────────────────────────
    RATE_LIMIT: float = 1.0          # requests per second per user
    RATE_LIMIT_WINDOW: int = 60      # window in seconds

    # ─── YouTube / yt-dlp ─────────────────────────────────────────────────────
    YTDLP_PROXY: Optional[str] = None
    YTDLP_COOKIES_FILE: Optional[str] = None

    # ─── Instagram ────────────────────────────────────────────────────────────
    INSTAGRAM_USERNAME: Optional[str] = None
    INSTAGRAM_PASSWORD: Optional[str] = None

    # ─── Language ─────────────────────────────────────────────────────────────
    DEFAULT_LANGUAGE: str = "uz"
    SUPPORTED_LANGUAGES: List[str] = ["uz", "ru", "en"]

    # ─── Logging ─────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FILE: str = "./logs/bot.log"

    # ─── Music Search ─────────────────────────────────────────────────────────
    MUSIC_SEARCH_RESULTS: int = 5
    MUSIC_CACHE_TTL: int = 1800

    @model_validator(mode="after")
    def validate_webhook(self):
        if self.USE_WEBHOOK and not self.WEBHOOK_URL:
            # Try to auto-detect on Render.com
            render_url = os.getenv("RENDER_EXTERNAL_URL", "")
            if render_url:
                self.WEBHOOK_URL = render_url
        return self


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()   