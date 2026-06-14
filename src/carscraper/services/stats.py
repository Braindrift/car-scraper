"""Aggregation queries for meta-information (CAR-8).

Per CLAUDE.md, routers/web never construct SQL/ORM queries directly — they
call into this module. This module provides:

- `avg_price_per_model`: average price per `(make, model, variant)` across
  *active* listings, for the stats summary view.
- `price_history`: the `(scraped_at, price)` series for a single
  `CarListing`'s `PriceSnapshot` rows, in chronological order, for the
  per-listing price-history chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, PriceSnapshot


@dataclass(frozen=True)
class ModelPriceStats:
    """Average price for a `(make, model, variant)` group across active listings."""

    make: str
    model: str
    variant: str | None
    avg_price: float
    listing_count: int


@dataclass(frozen=True)
class PricePoint:
    """A single `(scraped_at, price)` observation for a listing."""

    scraped_at: datetime
    price: int


def avg_price_per_model(session: Session) -> list[ModelPriceStats]:
    """Return average price per `(make, model, variant)` across active listings.

    Only `CarListing` rows with `active=True` and a non-null `price` are
    considered. Rows are ordered by `make`, then `model`, then `variant`
    (nulls first) for stable, predictable display order. Returns an empty
    list if there are no active listings with a price.
    """
    stmt = (
        select(
            CarListing.make,
            CarListing.model,
            CarListing.variant,
            func.avg(CarListing.price).label("avg_price"),
            func.count(CarListing.id).label("listing_count"),
        )
        .where(CarListing.active.is_(True))
        .where(CarListing.price.is_not(None))
        .group_by(CarListing.make, CarListing.model, CarListing.variant)
        .order_by(CarListing.make, CarListing.model, CarListing.variant)
    )

    return [
        ModelPriceStats(
            make=row.make,
            model=row.model,
            variant=row.variant,
            avg_price=float(row.avg_price),
            listing_count=row.listing_count,
        )
        for row in session.execute(stmt)
    ]


def price_history(session: Session, listing_id: int) -> list[PricePoint]:
    """Return the `(scraped_at, price)` series for `listing_id`, oldest-first.

    Used to drive the Chart.js price-history line chart on the listing
    detail page. Returns an empty list if the listing has no
    `PriceSnapshot` rows (e.g. it was never re-scraped, or doesn't exist).
    """
    stmt = (
        select(PriceSnapshot.scraped_at, PriceSnapshot.price)
        .where(PriceSnapshot.listing_id == listing_id)
        .order_by(PriceSnapshot.scraped_at)
    )

    return [PricePoint(scraped_at=row.scraped_at, price=row.price) for row in session.execute(stmt)]
