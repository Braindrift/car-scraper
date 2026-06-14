"""Query logic for `CarListing` rows.

Per CLAUDE.md, routers/web never construct SQL/ORM queries directly — they
call into this module. `list_car_listings` is the single entry point for the
dashboard's listings table (CAR-6): given a `Session` and a set of optional
filters, it returns the matching `CarListing` rows, most-recently-seen first.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from carscraper.db.models import CarListing, Dealer


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
    if filters.active_only:
        stmt = stmt.where(CarListing.active.is_(True))

    stmt = stmt.order_by(CarListing.last_seen.desc())

    return list(session.execute(stmt).scalars().all())


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
