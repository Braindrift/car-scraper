"""CRUD operations for `TrackedModel` rows.

Per CLAUDE.md, routers/web never construct SQL/ORM queries directly — they
call into this module. `TrackedModel` rows define which makes/models
(optionally variants) the user wants tracked; this module only manages those
rows. Using tracked models to filter/drive scrapers is out of scope (a later,
scraper-focused ticket).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.db.models import TrackedModel


def list_tracked_models(session: Session) -> list[TrackedModel]:
    """Return all `TrackedModel` rows, ordered by make then model then variant."""
    stmt = select(TrackedModel).order_by(
        TrackedModel.make, TrackedModel.model, TrackedModel.variant
    )
    return list(session.execute(stmt).scalars().all())


def create_tracked_model(
    session: Session, make: str, model: str, variant: str | None = None
) -> TrackedModel:
    """Create and persist a new `TrackedModel` row.

    `make` and `model` are required (callers should validate non-blank
    values before calling this); `variant` is optional and stored as `None`
    if blank.
    """
    tracked = TrackedModel(make=make, model=model, variant=variant or None)
    session.add(tracked)
    session.commit()
    return tracked


def delete_tracked_model(session: Session, tracked_model_id: int) -> bool:
    """Delete the `TrackedModel` row with the given id.

    Returns `True` if a row was deleted, `False` if no row with that id
    existed.
    """
    tracked = session.get(TrackedModel, tracked_model_id)
    if tracked is None:
        return False

    session.delete(tracked)
    session.commit()
    return True
