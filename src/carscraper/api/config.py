"""Config router.

Placeholder endpoints establishing the package structure per CLAUDE.md.
Real tracked-model configuration (the `TrackedModel` UI) lands in later
tickets and will call into `services/`, not query the ORM directly here.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/tracked-models")
def list_tracked_models() -> list[dict]:
    """List tracked make/model/variant configurations. Placeholder: empty list for now."""
    return []
