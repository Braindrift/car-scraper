"""CRUD operations for `TrackedModel` rows.

Per CLAUDE.md, routers/web never construct SQL/ORM queries directly — they
call into this module. `TrackedModel` rows define which makes/models
(optionally variants) the user wants tracked; this module only manages those
rows. Using tracked models to filter/drive scrapers is out of scope (a later,
scraper-focused ticket).
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from carscraper.config import settings
from carscraper.db.models import CarListing, TrackedModel

logger = logging.getLogger(__name__)


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
    existed. Does **not** remove associated `CarListing` rows or their
    images/snapshots — use `delete_tracked_model_with_data` for a full purge.
    """
    tracked = session.get(TrackedModel, tracked_model_id)
    if tracked is None:
        return False

    session.delete(tracked)
    session.commit()
    return True


def delete_tracked_model_with_data(
    session: Session,
    tracked_model_id: int,
    *,
    static_root: Path | None = None,
) -> bool:
    """Purge a tracked model and **all associated listing data**.

    Deletes, in order:

    1. `ListingImage` files from disk (under ``<static_root>/images/``).
    2. `ListingImage` rows (via SQLAlchemy cascade when the parent
       `CarListing` is deleted, but the files must be removed first).
    3. `PriceSnapshot` rows (likewise via cascade).
    4. `CarListing` rows whose ``make``/``model`` match the tracked model
       (case-insensitive, matching SQLite's ``LIKE`` semantics).
    5. The `TrackedModel` row itself.

    Returns `True` if the tracked model existed and was deleted, `False` if
    no row with ``tracked_model_id`` existed.

    `static_root` is injectable for tests (defaults to
    ``settings.static_root``).
    """
    tracked = session.get(TrackedModel, tracked_model_id)
    if tracked is None:
        return False

    root = static_root if static_root is not None else settings.static_root

    # Find all CarListing rows matching this make/model (case-insensitive).
    # SQLite LIKE is case-insensitive for ASCII by default; func.lower()
    # makes the match explicit and portable.
    stmt = select(CarListing).where(
        func.lower(CarListing.make) == func.lower(tracked.make),
        func.lower(CarListing.model) == func.lower(tracked.model),
    )
    listings = list(session.execute(stmt).scalars().all())

    # Delete on-disk image files before the DB rows are removed.
    for listing in listings:
        for image in listing.images:
            image_path = root / image.local_path
            try:
                image_path.unlink(missing_ok=True)
            except OSError as exc:
                logger.warning(
                    "Could not remove image file %s for listing %s: %s",
                    image_path,
                    listing.external_id,
                    exc,
                )
        # Remove the listing's image directory if it is now empty (best-effort).
        if listing.images:
            image_dir = root / "images" / listing.dealer.scraper_module / listing.external_id
            try:
                if image_dir.exists() and not any(image_dir.iterdir()):
                    shutil.rmtree(image_dir, ignore_errors=True)
            except OSError:
                pass

    # Delete CarListing rows — cascades remove PriceSnapshot, ListingImage,
    # and ScrapeLogEntry rows automatically.
    for listing in listings:
        session.delete(listing)

    # Delete the TrackedModel row itself.
    session.delete(tracked)
    session.commit()
    return True
