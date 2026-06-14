"""Application configuration.

Settings are loaded from environment variables / a local `.env` file via
pydantic-settings. Filled in further as later tickets need more config
(database path, dealer config, etc.).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(env_prefix="CARSCRAPER_", env_file=".env")

    app_name: str = "CarScraper 2.0"


settings = Settings()
