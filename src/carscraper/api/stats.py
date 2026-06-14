"""Stats router.

Placeholder endpoints establishing the package structure per CLAUDE.md.
Real aggregation queries (avg price per model, price trends, etc.) land in
later tickets and will call into `services/`, not query the ORM directly here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("/avg-price-per-model")
def avg_price_per_model() -> list[dict]:
    """Average price per tracked model. Placeholder: empty list for now."""
    return []
