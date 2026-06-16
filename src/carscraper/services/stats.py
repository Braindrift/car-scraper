"""Aggregation queries for meta-information (CAR-8, CAR-19, CAR-24, CAR-28).

Per CLAUDE.md, routers/web never construct SQL/ORM queries directly — they
call into this module. This module provides:

- `price_history`: the `(scraped_at, price)` series for a single
  `CarListing`'s `PriceSnapshot` rows, in chronological order, for the
  per-listing price-history chart.
- `model_overview_stats`: per-`(make, model)` rollup (variants combined) of
  avg/min/max/median price and listing count, for the rebuilt stats page
  (CAR-20).
- `year_bucket_stats`: per construction-year listing count and price range,
  with an "Unknown" bucket for listings with no `year`.
- `mileage_bucket_stats`: per fixed mileage-range listing count and price
  range, with "30000+" and "Unknown" buckets.

CAR-24: price aggregates (`avg_price`/`min_price`/`max_price`/`median_price`)
are computed only over "usable" prices — see `_usable_prices` — while
`listing_count` reflects every listing in scope (priced, unpriced, and
"low bid" listings whose price is excluded from the aggregates).
`excluded_count` reports how many of those in-scope listings were left out of
the price aggregates.

CAR-28: `model_overview_stats` normalises each listing's `(make, model)` to
the canonical casing defined in `TrackedModel` before grouping, so listings
that differ only in casing (e.g. "Ford S-MAX" vs "Ford S-Max") are merged
into one stats row.  See `_build_canonical_map` for details.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Case, case, select
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, PriceSnapshot, TrackedModel

# A non-null price counts toward avg/min/max/median only if it's at least
# this fraction of the preliminary median price for its scope. Prices below
# this threshold are treated as "low bid" placeholders (e.g. a KVD auction's
# current/leading bid) rather than real asking prices.
LOW_BID_THRESHOLD = 0.66

# Fixed mileage buckets (CAR-19), in display order, in Swedish mil (1 mil =
# 10 km) - `CarListing.mileage`'s unit. Each tuple is `(label,
# lower_bound_inclusive, upper_bound_inclusive)`; `upper_bound` is `None` for
# the open-ended "30000+" bucket. Listings with a null `mileage` fall into the
# separate "Unknown" bucket, handled outside this table.
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
class PricePoint:
    """A single `(scraped_at, price)` observation for a listing."""

    scraped_at: datetime
    price: int


@dataclass(frozen=True)
class ModelOverviewStats:
    """Price stats for a `(make, model)` group, with variants rolled up.

    `listing_count` is every listing in the group (priced, unpriced, or
    "low bid" — see module docstring). `avg_price`/`min_price`/`max_price`/
    `median_price` are computed only over "usable" prices and are `None` if
    the group has no usable price. `excluded_count` is the number of
    listings in the group with no usable price.
    """

    make: str
    model: str
    avg_price: float | None
    min_price: int | None
    max_price: int | None
    median_price: float | None
    listing_count: int
    excluded_count: int


@dataclass(frozen=True)
class YearBucketStats:
    """Listing count and price range for a construction-year bucket.

    `year` is `None` for the "Unknown" bucket (listings with no `year`).
    `listing_count` is every listing in the bucket; `avg_price`/`min_price`/
    `max_price`/`median_price` are computed only over "usable" prices (within
    the page's overall make/model scope — see module docstring) and are
    `None` if the bucket has no usable price. `excluded_count` is the number
    of listings in the bucket with no usable price.
    """

    year: int | None
    listing_count: int
    min_price: int | None
    max_price: int | None
    median_price: float | None
    excluded_count: int


@dataclass(frozen=True)
class MileageBucketStats:
    """Listing count and price range for a fixed mileage bucket.

    `bucket` is one of the labels in `MILEAGE_BUCKETS`, or
    `MILEAGE_BUCKET_UNKNOWN` for listings with no `mileage`. `listing_count`
    is every listing in the bucket; `avg_price`/`min_price`/`max_price`/
    `median_price` are computed only over "usable" prices (within the page's
    overall make/model scope — see module docstring) and are `None` if the
    bucket has no usable price. `excluded_count` is the number of listings in
    the bucket with no usable price.
    """

    bucket: str
    listing_count: int
    min_price: int | None
    max_price: int | None
    median_price: float | None
    excluded_count: int


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


def _usable_prices(prices: list[int]) -> list[int]:
    """Return the subset of `prices` usable for avg/min/max/median.

    Two-pass (CAR-24): a preliminary median is computed over all non-null
    `prices`. A price is "usable" only if it's `>= LOW_BID_THRESHOLD` times
    that preliminary median (filtering out "low bid" placeholders like a KVD
    auction's current/leading bid). If `prices` is empty, returns an empty
    list.
    """
    if not prices:
        return []

    preliminary_median = statistics.median(prices)
    threshold = LOW_BID_THRESHOLD * preliminary_median
    return [price for price in prices if price >= threshold]


@dataclass(frozen=True)
class _PriceStats:
    """Usable-price aggregates derived from `_usable_prices`."""

    avg_price: float | None
    min_price: int | None
    max_price: int | None
    median_price: float | None
    excluded_count: int


def _price_stats(all_prices: list[int | None]) -> _PriceStats:
    """Compute usable-price aggregates and the excluded count for a group.

    `all_prices` is every listing's `price` in the group/bucket (including
    `None` for unpriced listings). Returns `None` aggregates if no price is
    usable.
    """
    non_null_prices = [price for price in all_prices if price is not None]
    usable = _usable_prices(non_null_prices)
    excluded_count = len(all_prices) - len(usable)

    if not usable:
        return _PriceStats(
            avg_price=None,
            min_price=None,
            max_price=None,
            median_price=None,
            excluded_count=excluded_count,
        )

    return _PriceStats(
        avg_price=statistics.mean(usable),
        min_price=min(usable),
        max_price=max(usable),
        median_price=statistics.median(usable),
        excluded_count=excluded_count,
    )


def _build_canonical_map(session: Session) -> dict[tuple[str, str], tuple[str, str]]:
    """Return a lookup from lowercase `(make, model)` to canonical `(make, model)`.

    Loads all `TrackedModel` rows and indexes them by
    `(make.casefold(), model.casefold())`.  Used by `model_overview_stats`
    (CAR-28) to normalise each listing's raw make/model to the casing
    defined in `TrackedModel` before grouping — so "Ford S-MAX" and
    "Ford S-Max" merge into whichever casing `TrackedModel` stores.

    Listings whose `(make, model)` has no matching `TrackedModel` (after
    case-folding) are left under their own raw value; they still appear as a
    separate stats row so no data is silently discarded.
    """
    stmt = select(TrackedModel.make, TrackedModel.model)
    canonical: dict[tuple[str, str], tuple[str, str]] = {}
    for row in session.execute(stmt):
        key = (row.make.casefold(), row.model.casefold())
        # First entry wins if two TrackedModel rows somehow share a casefolded
        # key (the DB unique constraint is case-sensitive, so this is possible
        # though unlikely in practice).
        canonical.setdefault(key, (row.make, row.model))
    return canonical


def model_overview_stats(
    session: Session,
    make: str | None = None,
    model: str | None = None,
    include_inactive: bool = False,
) -> list[ModelOverviewStats]:
    """Return per-`(make, model)` price stats with variants rolled up.

    `listing_count` is every listing in the `(make, model)` group (priced,
    unpriced, or "low bid"). `avg_price`/`min_price`/`max_price`/
    `median_price` are computed only over "usable" prices for that group —
    see module docstring — and are `None` if the group has no usable price.
    `excluded_count` is the number of listings in the group with no usable
    price. `make`/`model` optionally narrow the listings considered (e.g. for
    the stats page's scope controls). By default (`include_inactive=False`)
    only `active=True` listings are included; `include_inactive=True`
    includes all listings regardless of `active`. Rows are ordered by `make`,
    then `model`. Returns an empty list if no listings match.
    """
    stmt = select(CarListing.make, CarListing.model, CarListing.price).order_by(
        CarListing.make, CarListing.model
    )
    stmt = _apply_active_filter(stmt, include_inactive)
    if make is not None:
        stmt = stmt.where(CarListing.make.ilike(make))
    if model is not None:
        stmt = stmt.where(CarListing.model.ilike(model))

    canonical_map = _build_canonical_map(session)

    prices_by_group: dict[tuple[str, str], list[int | None]] = defaultdict(list)
    for row in session.execute(stmt):
        # CAR-28: resolve raw make/model to TrackedModel-canonical casing.
        # Listings with no matching TrackedModel are grouped under their own
        # raw value so no data is silently discarded.
        canonical_key = canonical_map.get(
            (row.make.casefold(), row.model.casefold()),
            (row.make, row.model),
        )
        prices_by_group[canonical_key].append(row.price)

    results = []
    for (group_make, group_model), prices in prices_by_group.items():
        price_stats = _price_stats(prices)
        results.append(
            ModelOverviewStats(
                make=group_make,
                model=group_model,
                avg_price=price_stats.avg_price,
                min_price=price_stats.min_price,
                max_price=price_stats.max_price,
                median_price=price_stats.median_price,
                listing_count=len(prices),
                excluded_count=price_stats.excluded_count,
            )
        )

    return sorted(results, key=lambda row: (row.make, row.model))


def year_bucket_stats(
    session: Session,
    make: str | None = None,
    model: str | None = None,
    include_inactive: bool = False,
) -> list[YearBucketStats]:
    """Return per construction-year listing count and price stats.

    Listings with a null `year` are rolled up into a single bucket
    (`year=None` in the result). `make`/`model` optionally narrow the
    listings considered; `listing_count` is every listing in the bucket
    (priced, unpriced, or "low bid"). `avg_price`/`min_price`/`max_price`/
    `median_price` are computed only over "usable" prices — see module
    docstring — where the "scope" for the preliminary median is all listings
    matched by `make`/`model`/`include_inactive` (the page's current scope),
    not just this bucket. Buckets with no usable price report `None` for
    those fields. `excluded_count` is the number of listings in the bucket
    with no usable price. By default (`include_inactive=False`) only
    `active=True` listings are included. Rows are ordered by `year`
    ascending, with the "Unknown" (`year=None`) bucket last.
    """
    stmt = select(CarListing.year, CarListing.price)
    stmt = _apply_active_filter(stmt, include_inactive)
    if make is not None:
        stmt = stmt.where(CarListing.make.ilike(make))
    if model is not None:
        stmt = stmt.where(CarListing.model.ilike(model))

    prices_by_bucket: dict[int | None, list[int | None]] = defaultdict(list)
    scope_prices: list[int] = []
    for row in session.execute(stmt):
        prices_by_bucket[row.year].append(row.price)
        if row.price is not None:
            scope_prices.append(row.price)

    usable_in_scope = set(_usable_prices(scope_prices))

    results = []
    for year, prices in prices_by_bucket.items():
        usable = [price for price in prices if price is not None and price in usable_in_scope]
        excluded_count = len(prices) - len(usable)

        if usable:
            min_price: int | None = min(usable)
            max_price: int | None = max(usable)
            median_price: float | None = statistics.median(usable)
        else:
            min_price = None
            max_price = None
            median_price = None

        results.append(
            YearBucketStats(
                year=year,
                listing_count=len(prices),
                min_price=min_price,
                max_price=max_price,
                median_price=median_price,
                excluded_count=excluded_count,
            )
        )

    return sorted(results, key=lambda row: (row.year is None, row.year))


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
    """Return per fixed-mileage-bucket listing count and price stats.

    Buckets follow `MILEAGE_BUCKETS` (0-2000 ... 22001-30000, "30000+"),
    plus `MILEAGE_BUCKET_UNKNOWN` for listings with a null `mileage`.
    `make`/`model` optionally narrow the listings considered; `listing_count`
    is every listing in the bucket (priced, unpriced, or "low bid").
    `avg_price`/`min_price`/`max_price`/`median_price` are computed only over
    "usable" prices — see module docstring — where the "scope" for the
    preliminary median is all listings matched by
    `make`/`model`/`include_inactive` (the page's current scope), not just
    this bucket. Buckets with no usable price report `None` for those fields.
    `excluded_count` is the number of listings in the bucket with no usable
    price. By default (`include_inactive=False`) only `active=True` listings
    are included. Only buckets containing at least one matching listing are
    returned, ordered as in `MILEAGE_BUCKETS` with "Unknown" last.
    """
    bucket_expr = _mileage_bucket_case()

    stmt = select(bucket_expr.label("bucket"), CarListing.price)
    stmt = _apply_active_filter(stmt, include_inactive)
    if make is not None:
        stmt = stmt.where(CarListing.make.ilike(make))
    if model is not None:
        stmt = stmt.where(CarListing.model.ilike(model))

    prices_by_bucket: dict[str, list[int | None]] = defaultdict(list)
    scope_prices: list[int] = []
    for row in session.execute(stmt):
        prices_by_bucket[row.bucket].append(row.price)
        if row.price is not None:
            scope_prices.append(row.price)

    usable_in_scope = set(_usable_prices(scope_prices))

    rows_by_bucket: dict[str, MileageBucketStats] = {}
    for bucket, prices in prices_by_bucket.items():
        usable = [price for price in prices if price is not None and price in usable_in_scope]
        excluded_count = len(prices) - len(usable)

        if usable:
            min_price: int | None = min(usable)
            max_price: int | None = max(usable)
            median_price: float | None = statistics.median(usable)
        else:
            min_price = None
            max_price = None
            median_price = None

        rows_by_bucket[bucket] = MileageBucketStats(
            bucket=bucket,
            listing_count=len(prices),
            min_price=min_price,
            max_price=max_price,
            median_price=median_price,
            excluded_count=excluded_count,
        )

    bucket_order = [label for label, _, _ in MILEAGE_BUCKETS] + [MILEAGE_BUCKET_UNKNOWN]
    return [rows_by_bucket[bucket] for bucket in bucket_order if bucket in rows_by_bucket]
