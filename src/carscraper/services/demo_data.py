"""Demo/seed data for visually verifying the dashboard end to end (CAR-9).

**Dev/demo-only.** This module exists purely so the dashboard built across
CAR-5..8 (listings table, tracked-model config, stats, price-history charts)
can be populated with realistic-looking fake data and checked in a browser
without a real scraper. It must never be wired into a production scrape run.

All rows created here are tagged so they can be identified and removed:

- `Dealer.scraper_module` values use the `demo_` prefix.
- `CarListing.external_id` values use the `demo-` prefix.
- `TrackedModel` rows match a fixed demo set (see `_TRACKED_MODELS`).

`seed_demo_data` is safe to call repeatedly:
- By default it's idempotent — if demo dealers already exist, it does
  nothing further and reports the existing counts.
- With `reset=True`, it first deletes all demo rows (dealers, their
  listings, and those listings' price snapshots via cascade, plus the demo
  tracked models) and then reseeds from scratch.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.config import settings
from carscraper.db.models import CarListing, Dealer, ListingImage, TrackedModel
from carscraper.services.dealers import create_dealer, get_dealer_by_scraper_module
from carscraper.services.listings import add_price_snapshot, create_car_listing
from carscraper.services.tracked_models import create_tracked_model

# Prefix used for every demo dealer's `scraper_module`, so demo rows can be
# identified and cleared independently of any real dealer configuration.
_DEMO_DEALER_PREFIX = "demo_"

# Locally-bundled sample images, copied (never downloaded) into the static
# images tree so seeding/tests stay network-free. Cycled across the demo
# listings that get images (see `_LISTING_IMAGE_COUNTS`).
_DEMO_ASSETS_DIR = Path(__file__).resolve().parent / "demo_assets"
_DEMO_IMAGE_FILES = ["sample_1.png", "sample_2.png", "sample_3.png"]

_DEALERS = [
    {
        "name": "Bilia Stockholm (Demo)",
        "base_url": "https://www.bilia.se/stockholm",
        "scraper_module": f"{_DEMO_DEALER_PREFIX}bilia_stockholm",
    },
    {
        "name": "Hedin Bil Göteborg (Demo)",
        "base_url": "https://www.hedinbil.se/goteborg",
        "scraper_module": f"{_DEMO_DEALER_PREFIX}hedin_goteborg",
    },
    {
        "name": "Kia Center Malmö (Demo)",
        "base_url": "https://www.kiacenter.se/malmo",
        "scraper_module": f"{_DEMO_DEALER_PREFIX}kia_malmo",
    },
]

_TRACKED_MODELS = [
    {"make": "Volvo", "model": "V70", "variant": None},
    {"make": "Volvo", "model": "XC60", "variant": "T6 AWD"},
    {"make": "Kia", "model": "Sportage", "variant": None},
    {"make": "Toyota", "model": "RAV4", "variant": "Hybrid"},
    {"make": "BMW", "model": "320d", "variant": None},
]

# Each entry: dealer index (into _DEALERS), and the listing's static fields.
# `price` is the *current* (most recent) price; `price_history_offsets` are
# (days_ago, price) points used to build PriceSnapshot rows, oldest first,
# ending with (0, price) so the chart's latest point matches the listing.
_LISTINGS = [
    {
        "dealer": 0,
        "external_id": "demo-1001",
        "make": "Volvo",
        "model": "V70",
        "variant": "D4 Momentum",
        "year": 2018,
        "mileage": 98_000,
        "fuel_type": "Diesel",
        "transmission": "Automatic",
        "active": True,
        "price_history": [(60, 189_900), (30, 184_900), (0, 179_900)],
    },
    {
        "dealer": 0,
        "external_id": "demo-1002",
        "make": "Volvo",
        "model": "XC60",
        "variant": "T6 AWD Inscription",
        "year": 2020,
        "mileage": 54_000,
        "fuel_type": "Petrol",
        "transmission": "Automatic",
        "active": True,
        "price_history": [(45, 379_900), (15, 369_900), (0, 369_900)],
    },
    {
        "dealer": 0,
        "external_id": "demo-1003",
        "make": "Volvo",
        "model": "V60",
        "variant": "T4 Momentum",
        "year": 2019,
        "mileage": 71_500,
        "fuel_type": "Petrol",
        "transmission": "Automatic",
        "active": False,
        "price_history": [(90, 229_900), (45, 219_900), (10, 209_900)],
    },
    {
        "dealer": 1,
        "external_id": "demo-2001",
        "make": "Toyota",
        "model": "RAV4",
        "variant": "Hybrid AWD-i Style",
        "year": 2021,
        "mileage": 42_000,
        "fuel_type": "Hybrid",
        "transmission": "Automatic",
        "active": True,
        "price_history": [(50, 349_900), (20, 339_900), (0, 334_900)],
    },
    {
        "dealer": 1,
        "external_id": "demo-2002",
        "make": "Toyota",
        "model": "Corolla",
        "variant": "Hybrid Active",
        "year": 2022,
        "mileage": 28_000,
        "fuel_type": "Hybrid",
        "transmission": "Automatic",
        "active": True,
        "price_history": [(40, 259_900), (0, 254_900)],
    },
    {
        "dealer": 1,
        "external_id": "demo-2003",
        "make": "BMW",
        "model": "320d",
        "variant": "Touring xDrive",
        "year": 2019,
        "mileage": 87_000,
        "fuel_type": "Diesel",
        "transmission": "Automatic",
        "active": True,
        "price_history": [(70, 259_900), (35, 249_900), (0, 244_900)],
    },
    {
        "dealer": 1,
        "external_id": "demo-2004",
        "make": "BMW",
        "model": "118i",
        "variant": "Advantage",
        "year": 2017,
        "mileage": 110_000,
        "fuel_type": "Petrol",
        "transmission": "Manual",
        "active": False,
        "price_history": [(100, 149_900), (50, 144_900), (5, 139_900)],
    },
    {
        "dealer": 2,
        "external_id": "demo-3001",
        "make": "Kia",
        "model": "Sportage",
        "variant": "1.6 T-GDI GT-Line",
        "year": 2021,
        "mileage": 35_000,
        "fuel_type": "Petrol",
        "transmission": "Automatic",
        "active": True,
        "price_history": [(55, 309_900), (25, 304_900), (0, 299_900)],
    },
    {
        "dealer": 2,
        "external_id": "demo-3002",
        "make": "Kia",
        "model": "Niro",
        "variant": "Hybrid Plus",
        "year": 2020,
        "mileage": 61_000,
        "fuel_type": "Hybrid",
        "transmission": "Automatic",
        "active": True,
        "price_history": [(65, 229_900), (30, 224_900), (0, 219_900)],
    },
    {
        "dealer": 2,
        "external_id": "demo-3003",
        "make": "Volkswagen",
        "model": "Golf",
        "variant": "1.5 TSI Life",
        "year": 2021,
        "mileage": 39_000,
        "fuel_type": "Petrol",
        "transmission": "Manual",
        "active": True,
        "price_history": [(20, 219_900), (0, 214_900)],
    },
    {
        "dealer": 2,
        "external_id": "demo-3004",
        "make": "Volkswagen",
        "model": "Passat",
        "variant": "GT Sportscombi",
        "year": 2018,
        "mileage": 102_000,
        "fuel_type": "Diesel",
        "transmission": "Automatic",
        "active": False,
        "price_history": [(80, 219_900), (40, 209_900), (0, 199_900)],
    },
]


# How many sample images each demo listing gets, keyed by external_id. A few
# listings get multiple images (to exercise carousel prev/next), one gets a
# single image, and the rest are left imageless (to exercise the "no images"
# placeholder). Listings not listed here get zero images.
_LISTING_IMAGE_COUNTS = {
    "demo-1001": 3,
    "demo-1002": 2,
    "demo-2001": 3,
    "demo-3001": 1,
}


@dataclass(frozen=True)
class SeedSummary:
    """Row counts after seeding, for the CLI to report."""

    dealers: int
    tracked_models: int
    listings: int
    price_snapshots: int
    images: int
    reset: bool


def _demo_dealer_slugs() -> set[str]:
    return {d["scraper_module"] for d in _DEALERS}


def _seed_listing_images(listing: CarListing, dealer_slug: str, count: int) -> int:
    """Copy `count` bundled sample images for `listing` and add rows.

    Mirrors `services/images.py`'s on-disk layout
    (``<static_root>/images/<slug>/<external_id>/<n>.<ext>``) and stores the
    same static-root-relative `local_path`, but copies from locally-bundled
    files instead of downloading — so seeding stays network-free. Returns the
    number of images created.
    """
    if count <= 0:
        return 0

    target_dir = settings.static_root / "images" / dealer_slug / listing.external_id
    target_dir.mkdir(parents=True, exist_ok=True)

    for position in range(count):
        source = _DEMO_ASSETS_DIR / _DEMO_IMAGE_FILES[position % len(_DEMO_IMAGE_FILES)]
        ext = source.suffix.lstrip(".")
        file_path = target_dir / f"{position}.{ext}"
        shutil.copyfile(source, file_path)
        local_path = file_path.relative_to(settings.static_root).as_posix()
        listing.images.append(ListingImage(local_path=local_path, position=position))

    return count


def _clear_demo_data(session: Session) -> None:
    """Delete all demo dealers (and their listings/snapshots/images via
    cascade) and demo tracked models, plus the demo image files on disk.

    Used by `reset=True` to wipe previously-seeded demo rows before
    reseeding from scratch.
    """
    for slug in _demo_dealer_slugs():
        dealer = get_dealer_by_scraper_module(session, slug)
        if dealer is not None:
            session.delete(dealer)
        # Remove the dealer's static image tree so reseeding starts clean.
        dealer_image_dir = settings.static_root / "images" / slug
        if dealer_image_dir.exists():
            shutil.rmtree(dealer_image_dir)

    for tm in _TRACKED_MODELS:
        stmt = select(TrackedModel).where(
            TrackedModel.make == tm["make"],
            TrackedModel.model == tm["model"],
            TrackedModel.variant == tm["variant"],
        )
        existing = session.execute(stmt).scalar_one_or_none()
        if existing is not None:
            session.delete(existing)

    session.commit()


def _demo_data_exists(session: Session) -> bool:
    """Return `True` if any demo dealer already exists."""
    stmt = select(Dealer.id).where(Dealer.scraper_module.in_(_demo_dealer_slugs())).limit(1)
    return session.execute(stmt).first() is not None


def _current_counts(session: Session) -> SeedSummary:
    dealers = [
        d
        for d in (get_dealer_by_scraper_module(session, slug) for slug in _demo_dealer_slugs())
        if d is not None
    ]
    listing_count = sum(len(d.listings) for d in dealers)
    snapshot_count = sum(len(listing.price_snapshots) for d in dealers for listing in d.listings)
    image_count = sum(len(listing.images) for d in dealers for listing in d.listings)

    tracked_count = 0
    for tm in _TRACKED_MODELS:
        stmt = select(TrackedModel).where(
            TrackedModel.make == tm["make"],
            TrackedModel.model == tm["model"],
            TrackedModel.variant == tm["variant"],
        )
        if session.execute(stmt).scalar_one_or_none() is not None:
            tracked_count += 1

    return SeedSummary(
        dealers=len(dealers),
        tracked_models=tracked_count,
        listings=listing_count,
        price_snapshots=snapshot_count,
        images=image_count,
        reset=False,
    )


def seed_demo_data(session: Session, reset: bool = False) -> SeedSummary:
    """Populate the database with demo `Dealer`, `TrackedModel`,
    `CarListing`, and `PriceSnapshot` rows.

    **Dev/demo-only** — never call this against a database holding real
    scraped data without `reset=False` (the default), since `reset=True`
    deletes any existing demo rows (identified by the `demo_`/`demo-`
    prefixes) before reseeding.

    - `reset=False` (default): idempotent. If demo dealers already exist,
      no new rows are created and the current demo row counts are returned.
    - `reset=True`: deletes all existing demo rows first, then reseeds from
      scratch.

    Returns a `SeedSummary` with the resulting row counts.
    """
    if reset:
        _clear_demo_data(session)
    elif _demo_data_exists(session):
        return _current_counts(session)

    dealers: list[Dealer] = []
    for dealer_data in _DEALERS:
        dealers.append(
            create_dealer(
                session,
                name=dealer_data["name"],
                base_url=dealer_data["base_url"],
                scraper_module=dealer_data["scraper_module"],
            )
        )

    for tm in _TRACKED_MODELS:
        create_tracked_model(session, make=tm["make"], model=tm["model"], variant=tm["variant"])

    # Naive UTC timestamp, matching the `DateTime` columns' `func.now()`
    # server defaults (which on SQLite are naive UTC).
    now = datetime.now(UTC).replace(tzinfo=None)
    snapshot_count = 0
    image_count = 0
    for listing_data in _LISTINGS:
        dealer = dealers[listing_data["dealer"]]
        history = listing_data["price_history"]
        current_price = history[-1][1]

        first_seen = now - timedelta(days=history[0][0])
        # Active listings were "last seen" in today's (hypothetical) scrape
        # run; inactive ones stopped appearing a day after their last price
        # snapshot.
        last_seen = now if listing_data["active"] else now - timedelta(days=1)

        listing = create_car_listing(
            session,
            dealer_id=dealer.id,
            external_id=listing_data["external_id"],
            url=f"{dealer.base_url}/listings/{listing_data['external_id']}",
            make=listing_data["make"],
            model=listing_data["model"],
            variant=listing_data["variant"],
            year=listing_data["year"],
            mileage=listing_data["mileage"],
            price=current_price,
            fuel_type=listing_data["fuel_type"],
            transmission=listing_data["transmission"],
            first_seen=first_seen,
            last_seen=last_seen,
            active=listing_data["active"],
        )

        for days_ago, price in history:
            add_price_snapshot(
                session,
                listing_id=listing.id,
                price=price,
                scraped_at=now - timedelta(days=days_ago),
            )
            snapshot_count += 1

        wanted_images = _LISTING_IMAGE_COUNTS.get(listing_data["external_id"], 0)
        if wanted_images:
            image_count += _seed_listing_images(listing, dealer.scraper_module, wanted_images)
            session.commit()

    return SeedSummary(
        dealers=len(dealers),
        tracked_models=len(_TRACKED_MODELS),
        listings=len(_LISTINGS),
        price_snapshots=snapshot_count,
        images=image_count,
        reset=reset,
    )
