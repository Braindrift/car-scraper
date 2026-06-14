"""Dealers router.

Placeholder endpoints establishing the package structure per CLAUDE.md.
Real dealer CRUD/management lands in later tickets and will call into
`services/`, not query the ORM directly here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/dealers", tags=["dealers"])


@router.get("")
def list_dealers() -> list[dict]:
    """List configured dealers. Placeholder: always returns an empty list for now."""
    return []
