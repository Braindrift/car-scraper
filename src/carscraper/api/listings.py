"""Listings router.

Placeholder endpoints establishing the package structure per CLAUDE.md.
Real listing queries (filtering, price history, etc.) land in later tickets
and will call into `services/`, not query the ORM directly here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/listings", tags=["listings"])


@router.get("")
def list_listings() -> list[dict]:
    """List car listings. Placeholder: always returns an empty list for now."""
    return []
