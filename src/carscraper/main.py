"""FastAPI application entrypoint.

Template wiring (`web/`) is added by later tickets.
"""

from __future__ import annotations

from fastapi import FastAPI

from carscraper.api import config, dealers, listings, stats
from carscraper.config import settings


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(title=settings.app_name)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness check used by `uvicorn`/monitoring."""
        return {"status": "ok"}

    app.include_router(listings.router)
    app.include_router(dealers.router)
    app.include_router(config.router)
    app.include_router(stats.router)

    return app


app = create_app()
