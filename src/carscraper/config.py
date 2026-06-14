"""Application configuration.

Settings are loaded from environment variables / a local `.env` file via
pydantic-settings. Filled in further as later tickets need more config
(dealer config, etc.).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: src/carscraper/config.py -> src/carscraper -> src -> <repo root>
_REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(env_prefix="CARSCRAPER_", env_file=".env")

    app_name: str = "CarScraper 2.0"

    # SQLAlchemy database URL. Defaults to a SQLite file at the repo root,
    # which keeps "back up the app" as simple as "copy this file".
    database_url: str = f"sqlite:///{(_REPO_ROOT / 'carscraper.db').as_posix()}"


settings = Settings()
