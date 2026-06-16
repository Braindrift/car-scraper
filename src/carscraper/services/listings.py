"""Query logic for `CarListing` rows.

Per CLAUDE.md, routers/web never construct SQL/ORM queries directly — they
call into this module. `list_car_listings` is the single entry point for the
dashboard's listings table (CAR-6): given a `Session` and a set of optional
filters, it returns the matching `CarListing` rows, most-recently-seen first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from carscraper.config import settings
from carscraper.db.models import (
    CarListing,
    Dealer,
    PriceSnapshot,
    ScrapeLogEntry,
    ScrapeRun,
)
from carscraper.services.scrape_results import CHANGE_UPDATED

logger = logging.getLogger(__name__)

# Dashboard status values for a listing relative to when the user last viewed
# it (CAR-14). This is a service-level concept (the templates only render the
# resulting value), mirroring how change-type constants live in
# `services/scrape_results.py` rather than on the models.
STATUS_NEW = "new"
STATUS_UPDATED = "updated"
STATUS_SEEN = "seen"


def _now() -> datetime:
    """Naive UTC timestamp, matching the models' `func.now()` columns.

    The `DateTime` columns are timezone-naive (see
    `services/scrape_results._now`), so service-set timestamps drop tzinfo to
    compare cleanly against stored values.
    """
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass(frozen=True)
class ListingFilters:
    """Optional filters for `list_car_listings`.

    Every field is optional; an unset (`None`/`False`) field is not applied,
    so calling `list_car_listings(session)` with no filters returns all
    listings.
    """

    make: str | None = None
    model: str | None = None
    dealer_id: int | None = None
    min_price: int | None = None
    max_price: int | None = None
    active_only: bool = False
    # Tri-state discarded filter: `None` applies no filter, `False` returns
    # only non-discarded listings (the main dashboard), `True` returns only
    # discarded ones (the Discarded page).
    discarded: bool | None = None
    # Exact construction-year match, for drilling down from a year bucket
    # (CAR-22).
    year: int | None = None
    # Mileage range bounds, for drilling down from a mileage bucket (CAR-22).
    min_mileage: int | None = None
    max_mileage: int | None = None
    # When set, restrict to listings with a null `year`/`mileage` — drilling
    # down from the "Unknown" year/mileage bucket (CAR-22). Takes precedence
    # over `year`/`min_mileage`/`max_mileage` when set.
    year_unknown: bool = False
    mileage_unknown: bool = False


def list_car_listings(session: Session, filters: ListingFilters | None = None) -> list[CarListing]:
    """Return `CarListing` rows matching `filters`, newest-first.

    `filters` defaults to `ListingFilters()` (no filters applied), which
    returns every listing in the database. Results are ordered by
    `last_seen` descending so the most recently-scraped listings surface
    first.
    """
    filters = filters or ListingFilters()

    # Eagerly load `dealer` so templates can render `listing.dealer.name`
    # after the session used here has been closed (the web routes render
    # templates outside the `with get_session()` block).
    stmt = select(CarListing).options(selectinload(CarListing.dealer))

    if filters.make is not None:
        stmt = stmt.where(CarListing.make == filters.make)
    if filters.model is not None:
        stmt = stmt.where(CarListing.model == filters.model)
    if filters.dealer_id is not None:
        stmt = stmt.where(CarListing.dealer_id == filters.dealer_id)
    if filters.min_price is not None:
        stmt = stmt.where(CarListing.price >= filters.min_price)
    if filters.max_price is not None:
        stmt = stmt.where(CarListing.price <= filters.max_price)
    if filters.year_unknown:
        stmt = stmt.where(CarListing.year.is_(None))
    elif filters.year is not None:
        stmt = stmt.where(CarListing.year == filters.year)
    if filters.mileage_unknown:
        stmt = stmt.where(CarListing.mileage.is_(None))
    else:
        if filters.min_mileage is not None:
            stmt = stmt.where(CarListing.mileage >= filters.min_mileage)
        if filters.max_mileage is not None:
            stmt = stmt.where(CarListing.mileage <= filters.max_mileage)
    if filters.active_only:
        stmt = stmt.where(CarListing.active.is_(True))
    if filters.discarded is not None:
        stmt = stmt.where(CarListing.discarded.is_(filters.discarded))

    stmt = stmt.order_by(CarListing.last_seen.desc())

    return list(session.execute(stmt).scalars().all())


def get_listing(session: Session, listing_id: int) -> CarListing | None:
    """Return a single `CarListing` by id, with its `dealer` eagerly loaded.

    Returns `None` if no listing with `listing_id` exists. Used by the
    listing detail view (CAR-8).
    """
    stmt = (
        select(CarListing)
        .options(selectinload(CarListing.dealer), selectinload(CarListing.images))
        .where(CarListing.id == listing_id)
    )
    return session.execute(stmt).scalar_one_or_none()


def list_dealers_with_listings(session: Session) -> list[Dealer]:
    """Return `Dealer` rows that have at least one `CarListing`, by name.

    Used to populate the dealer dropdown in the listings filter form — only
    dealers with listings are relevant choices there.
    """
    stmt = (
        select(Dealer)
        .join(CarListing, CarListing.dealer_id == Dealer.id)
        .distinct()
        .order_by(Dealer.name)
    )
    return list(session.execute(stmt).scalars().all())


def create_car_listing(
    session: Session,
    dealer_id: int,
    external_id: str,
    url: str,
    make: str,
    model: str,
    variant: str | None = None,
    year: int | None = None,
    mileage: int | None = None,
    price: int | None = None,
    fuel_type: str | None = None,
    transmission: str | None = None,
    first_seen: datetime | None = None,
    last_seen: datetime | None = None,
    active: bool = True,
) -> CarListing:
    """Create and persist a new `CarListing` row.

    `(dealer_id, external_id)` should be unique (the natural key for a
    listing on a dealer's site); callers are responsible for avoiding
    duplicates. `first_seen`/`last_seen` default to the column defaults
    (now) if not provided.
    """
    kwargs: dict[str, object] = {
        "dealer_id": dealer_id,
        "external_id": external_id,
        "url": url,
        "make": make,
        "model": model,
        "variant": variant,
        "year": year,
        "mileage": mileage,
        "price": price,
        "fuel_type": fuel_type,
        "transmission": transmission,
        "active": active,
    }
    if first_seen is not None:
        kwargs["first_seen"] = first_seen
    if last_seen is not None:
        kwargs["last_seen"] = last_seen

    listing = CarListing(**kwargs)
    session.add(listing)
    session.commit()
    return listing


def add_price_snapshot(
    session: Session,
    listing_id: int,
    price: int,
    scraped_at: datetime | None = None,
) -> PriceSnapshot:
    """Create and persist a new `PriceSnapshot` row for `listing_id`.

    `scraped_at` defaults to the column default (now) if not provided; pass
    an explicit value (e.g. to seed historical price points for the
    price-history chart).
    """
    kwargs: dict[str, object] = {"listing_id": listing_id, "price": price}
    if scraped_at is not None:
        kwargs["scraped_at"] = scraped_at

    snapshot = PriceSnapshot(**kwargs)
    session.add(snapshot)
    session.commit()
    return snapshot


def _listing_ids_updated_since_view(session: Session, listings: list[CarListing]) -> set[int]:
    """Return ids of `listings` with a price change since the user last viewed.

    A listing counts as updated when it has a `ScrapeLogEntry` with
    `change_type="updated"` whose `ScrapeRun.finished_at` is later than the
    listing's `last_viewed_at` (CAR-12 records one such entry per price change).
    Listings never viewed (`last_viewed_at` is null) are reported NEW rather
    than UPDATED, so they're excluded here.
    """
    candidates = {
        listing.id: listing.last_viewed_at
        for listing in listings
        if listing.last_viewed_at is not None
    }
    if not candidates:
        return set()

    stmt = (
        select(ScrapeLogEntry.listing_id, ScrapeRun.finished_at)
        .join(ScrapeRun, ScrapeLogEntry.scrape_run_id == ScrapeRun.id)
        .where(ScrapeLogEntry.listing_id.in_(candidates))
        .where(ScrapeLogEntry.change_type == CHANGE_UPDATED)
        .where(ScrapeRun.finished_at.is_not(None))
    )

    updated: set[int] = set()
    for listing_id, finished_at in session.execute(stmt):
        if finished_at is not None and finished_at > candidates[listing_id]:
            updated.add(listing_id)
    return updated


def listing_statuses(session: Session, listings: list[CarListing]) -> dict[int, str]:
    """Map each listing's id to its dashboard status (NEW / UPDATED / SEEN).

    Rules (CAR-14):
    - **NEW** — `last_viewed_at` is null, or `first_seen` is later than it.
    - **UPDATED** — a price change (an "updated" `ScrapeLogEntry`) landed in a
      `ScrapeRun` that finished after `last_viewed_at`.
    - **SEEN** — otherwise; the caller renders `last_seen` as a plain date.

    NEW takes precedence over UPDATED: an unseen listing is simply new.
    """
    updated_ids = _listing_ids_updated_since_view(session, listings)

    statuses: dict[int, str] = {}
    for listing in listings:
        if listing.last_viewed_at is None or listing.first_seen > listing.last_viewed_at:
            statuses[listing.id] = STATUS_NEW
        elif listing.id in updated_ids:
            statuses[listing.id] = STATUS_UPDATED
        else:
            statuses[listing.id] = STATUS_SEEN
    return statuses


def mark_listing_viewed(session: Session, listing_id: int) -> None:
    """Record that the user just viewed `listing_id`, clearing its badge.

    Sets `last_viewed_at = now()` and commits. A no-op (no commit) if the
    listing doesn't exist, so callers can call this unconditionally on the
    detail route. After this, the listing reads as SEEN on the next dashboard
    load until a later scrape produces a fresh price change.
    """
    listing = session.get(CarListing, listing_id)
    if listing is None:
        return
    listing.last_viewed_at = _now()
    session.commit()


def delete_car_listing(
    session: Session,
    listing_id: int,
    *,
    static_root: Path | None = None,
) -> bool:
    """Permanently delete a single `CarListing` and all its associated data.

    Deletes, in order:

    1. `ListingImage` files from disk (under ``<static_root>/images/``).
    2. `ListingImage` rows (via SQLAlchemy cascade when the parent
       `CarListing` is deleted, but the files must be removed first).
    3. `PriceSnapshot` rows (likewise via cascade).
    4. `ScrapeLogEntry` rows (likewise via cascade).
    5. The `CarListing` row itself.

    No `TrackedModel` is touched — use `delete_tracked_model_with_data` in
    `services/tracked_models.py` to purge an entire make/model at once.

    Returns `True` if the listing existed and was deleted, `False` if no row
    with `listing_id` existed.

    `static_root` is injectable for tests (defaults to
    ``settings.static_root``).
    """
    listing = session.get(CarListing, listing_id, options=[selectinload(CarListing.images)])
    if listing is None:
        return False

    root = static_root if static_root is not None else settings.static_root

    # Delete on-disk image files before the DB rows are removed.
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
        # `dealer.scraper_module` is not loaded here; derive it from the image path.
        # Image paths are ``images/<dealer_slug>/<external_id>/<n>.<ext>``.
        first_path = root / listing.images[0].local_path
        image_dir = first_path.parent
        try:
            if image_dir.exists() and not any(image_dir.iterdir()):
                import shutil

                shutil.rmtree(image_dir, ignore_errors=True)
        except OSError:
            pass

    # Delete the CarListing row — cascades remove PriceSnapshot, ListingImage,
    # and ScrapeLogEntry rows automatically.
    session.delete(listing)
    session.commit()
    return True


def set_listing_discarded(session: Session, listing_id: int, discarded: bool) -> CarListing | None:
    """Set `listing_id`'s `discarded` flag, returning the updated listing.

    Discarding (`discarded=True`) hides a listing from the main dashboard but
    keeps the row — it's still scraped/updated and still counts in stats — and
    surfaces it on the Discarded page. Restoring (`discarded=False`) reverses
    that. Returns `None` (no commit) if the listing doesn't exist.
    """
    listing = session.get(CarListing, listing_id)
    if listing is None:
        return None
    listing.discarded = discarded
    session.commit()
    return listing
