"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from carscraper.api import config, dealers, listings, stats
from carscraper.config import settings
from carscraper.web import routes as web_routes

STATIC_DIR = Path(__file__).resolve().parent / "web" / "static"


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application."""
    app = FastAPI(title=settings.app_name)

    @app.get("/health")
    def health() -> dict[str, str]:
        """Liveness check used by `uvicorn`/monitoring."""
        return {"status": "ok"}

    app.include_router(web_routes.router)
    app.include_router(listings.router)
    app.include_router(dealers.router)
    app.include_router(config.router)
    app.include_router(stats.router)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    return app


app = create_app()
