"""FastAPI routers (listings, dealers, config, stats).

Routers are thin: validate input, call a service, return a schema.
"""

from __future__ import annotations

from carscraper.api import config, dealers, listings, stats

__all__ = ["config", "dealers", "listings", "stats"]
