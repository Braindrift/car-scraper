"""Aggregation queries for meta-information (CAR-8, CAR-19).

Per CLAUDE.md, routers/web never construct SQL/ORM queries directly — they
call into this module. This module provides:

- `avg_price_per_model`: average price per `(make, model, variant)` across
  *active* listings, for the stats summary view.
- `price_history`: the `(scraped_at, price)` series for a single
  `CarListing`'s `PriceSnapshot` rows, in chronological order, for the
  per-listing price-history chart.
- `model_overview_stats`: per-`(make, model)` rollup (variants combined) of
  avg/min/max price and listing count, for the rebuilt stats page (CAR-20).
- `year_bucket_stats`: per construction-year listing count and price range,
  with an "Unknown" bucket for listings with no `year`.
- `mileage_bucket_stats`: per fixed mileage-range listing count and price
  range, with "30000+" and "Unknown" buckets.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Case, case, func, select
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, PriceSnapshot

# Fixed mileage buckets (CAR-19), in display order. Each tuple is
# `(label, lower_bound_inclusive, upper_bound_inclusive)`; `upper_bound`
# is `None` for the open-ended "30000+" bucket. Listings with a null
# `mileage` fall into the separate "Unknown" bucket, handled outside this
# table.
MILEAGE_BUCKETS: tuple[tuple[str, int, int | None], ...] = (
    ("0-2000", 0, 2000),
    ("2001-5000", 2001, 5000),
    ("5001-8000", 5001, 8000),
    ("8001-10000", 8001, 10000),
    ("10001-14000", 10001, 14000),
    ("14001-18000", 14001, 18000),
    ("18001-22000", 18001, 22000),
    ("22001-30000", 22001, 30000),
    ("30000+", 30001, None),
)
MILEAGE_BUCKET_UNKNOWN = "Unknown"


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


@dataclass(frozen=True)
class ModelOverviewStats:
    """Price stats for a `(make, model)` group, with variants rolled up."""

    make: str
    model: str
    avg_price: float
    min_price: int
    max_price: int
    listing_count: int


@dataclass(frozen=True)
class YearBucketStats:
    """Listing count and price range for a construction-year bucket.

    `year` is `None` for the "Unknown" bucket (listings with no `year`).
    """

    year: int | None
    listing_count: int
    min_price: int
    max_price: int


@dataclass(frozen=True)
class MileageBucketStats:
    """Listing count and price range for a fixed mileage bucket.

    `bucket` is one of the labels in `MILEAGE_BUCKETS`, or
    `MILEAGE_BUCKET_UNKNOWN` for listings with no `mileage`.
    """

    bucket: str
    listing_count: int
    min_price: int
    max_price: int


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


def _apply_active_filter(stmt, include_inactive: bool):  # type: ignore[no-untyped-def]
    """Restrict `stmt` to active listings unless `include_inactive` is set."""
    if not include_inactive:
        return stmt.where(CarListing.active.is_(True))
    return stmt


def model_overview_stats(
    session: Session, include_inactive: bool = False
) -> list[ModelOverviewStats]:
    """Return per-`(make, model)` price stats with variants rolled up.

    Only listings with a non-null `price` are considered. By default
    (`include_inactive=False`) only `active=True` listings are included;
    `include_inactive=True` includes all listings regardless of `active`.
    Rows are ordered by `make`, then `model`. Returns an empty list if no
    listings match.
    """
    stmt = (
        select(
            CarListing.make,
            CarListing.model,
            func.avg(CarListing.price).label("avg_price"),
            func.min(CarListing.price).label("min_price"),
            func.max(CarListing.price).label("max_price"),
            func.count(CarListing.id).label("listing_count"),
        )
        .where(CarListing.price.is_not(None))
        .group_by(CarListing.make, CarListing.model)
        .order_by(CarListing.make, CarListing.model)
    )
    stmt = _apply_active_filter(stmt, include_inactive)

    return [
        ModelOverviewStats(
            make=row.make,
            model=row.model,
            avg_price=float(row.avg_price),
            min_price=row.min_price,
            max_price=row.max_price,
            listing_count=row.listing_count,
        )
        for row in session.execute(stmt)
    ]


def year_bucket_stats(
    session: Session,
    make: str | None = None,
    model: str | None = None,
    include_inactive: bool = False,
) -> list[YearBucketStats]:
    """Return per construction-year listing count and price range.

    Listings with a null `year` are rolled up into a single bucket
    (`year=None` in the result). `make`/`model` optionally narrow the
    listings considered; only listings with a non-null `price` are
    included. By default (`include_inactive=False`) only `active=True`
    listings are included. Rows are ordered by `year` ascending, with the
    "Unknown" (`year=None`) bucket last.
    """
    stmt = (
        select(
            CarListing.year,
            func.count(CarListing.id).label("listing_count"),
            func.min(CarListing.price).label("min_price"),
            func.max(CarListing.price).label("max_price"),
        )
        .where(CarListing.price.is_not(None))
        .group_by(CarListing.year)
        .order_by(CarListing.year.is_(None), CarListing.year)
    )
    stmt = _apply_active_filter(stmt, include_inactive)
    if make is not None:
        stmt = stmt.where(CarListing.make == make)
    if model is not None:
        stmt = stmt.where(CarListing.model == model)

    return [
        YearBucketStats(
            year=row.year,
            listing_count=row.listing_count,
            min_price=row.min_price,
            max_price=row.max_price,
        )
        for row in session.execute(stmt)
    ]


def _mileage_bucket_case() -> Case[str]:
    """Build the `CASE` expression mapping `CarListing.mileage` to a bucket label.

    Null `mileage` maps to `MILEAGE_BUCKET_UNKNOWN`; every other value maps
    to the matching label in `MILEAGE_BUCKETS` (the last bucket, "30000+",
    has no upper bound).
    """
    whens = []
    for label, lower, upper in MILEAGE_BUCKETS:
        condition = CarListing.mileage >= lower
        if upper is not None:
            condition = condition & (CarListing.mileage <= upper)
        whens.append((condition, label))

    return case(*whens, else_=MILEAGE_BUCKET_UNKNOWN)


def mileage_bucket_stats(
    session: Session,
    make: str | None = None,
    model: str | None = None,
    include_inactive: bool = False,
) -> list[MileageBucketStats]:
    """Return per fixed-mileage-bucket listing count and price range.

    Buckets follow `MILEAGE_BUCKETS` (0-2000 ... 22001-30000, "30000+"),
    plus `MILEAGE_BUCKET_UNKNOWN` for listings with a null `mileage`.
    `make`/`model` optionally narrow the listings considered; only listings
    with a non-null `price` are included. By default
    (`include_inactive=False`) only `active=True` listings are included.
    Only buckets containing at least one matching listing are returned,
    ordered as in `MILEAGE_BUCKETS` with "Unknown" last.
    """
    bucket_expr = _mileage_bucket_case()

    stmt = (
        select(
            bucket_expr.label("bucket"),
            func.count(CarListing.id).label("listing_count"),
            func.min(CarListing.price).label("min_price"),
            func.max(CarListing.price).label("max_price"),
        )
        .where(CarListing.price.is_not(None))
        .group_by(bucket_expr)
    )
    stmt = _apply_active_filter(stmt, include_inactive)
    if make is not None:
        stmt = stmt.where(CarListing.make == make)
    if model is not None:
        stmt = stmt.where(CarListing.model == model)

    rows_by_bucket = {
        row.bucket: MileageBucketStats(
            bucket=row.bucket,
            listing_count=row.listing_count,
            min_price=row.min_price,
            max_price=row.max_price,
        )
        for row in session.execute(stmt)
    }

    bucket_order = [label for label, _, _ in MILEAGE_BUCKETS] + [MILEAGE_BUCKET_UNKNOWN]
    return [rows_by_bucket[bucket] for bucket in bucket_order if bucket in rows_by_bucket]
