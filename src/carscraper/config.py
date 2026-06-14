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

# Web static root (the directory mounted at /static). Downloaded listing
# images live under <static_root>/images/... and are served from there.
_STATIC_ROOT = Path(__file__).resolve().parent / "web" / "static"


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(env_prefix="CARSCRAPER_", env_file=".env")

    app_name: str = "CarScraper 2.0"

    # SQLAlchemy database URL. Defaults to a SQLite file at the repo root,
    # which keeps "back up the app" as simple as "copy this file".
    database_url: str = f"sqlite:///{(_REPO_ROOT / 'carscraper.db').as_posix()}"

    # Filesystem path to the web static root (mounted at /static). Listing
    # images are downloaded under `<static_root>/images/<dealer_slug>/...`.
    # Overridable in tests so downloads land in a temp dir, not the package.
    static_root: Path = _STATIC_ROOT


settings = Settings()
