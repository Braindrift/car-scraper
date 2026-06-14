"""FastAPI application entrypoint.

API routers and template wiring are added by later tickets (api/, web/).
"""

from __future__ import annotations

from fastapi import FastAPI

from carscraper.config import settings


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(title=settings.app_name)
    return app


app = create_app()
