"""Tests for `services.demo_data` (CAR-9).

`seed_demo_data` is exercised against a temporary SQLite database, covering:

- the initial seed produces the expected row counts across `Dealer`,
  `TrackedModel`, `CarListing`, and `PriceSnapshot`;
- re-running without `--reset` is idempotent (no duplicate rows);
- `reset=True` wipes and reseeds without accumulating rows.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from carscraper.config import settings
from carscraper.db.models import CarListing, Dealer, ListingImage, PriceSnapshot, TrackedModel
from carscraper.db.session import Base, create_db_engine
from carscraper.services.demo_data import (
    _DEALERS,
    _LISTING_IMAGE_COUNTS,
    _LISTINGS,
    _TRACKED_MODELS,
    ClearSummary,
    clear_demo_data,
    seed_demo_data,
)


@pytest.fixture
def session(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    db_path = tmp_path / "demo_data_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Seed images into a temp static root, never the package's static tree.
    monkeypatch.setattr(settings, "static_root", tmp_path / "static")

    with Session(engine) as session:
        yield session

    engine.dispose()


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


_EXPECTED_SNAPSHOTS = sum(len(listing["price_history"]) for listing in _LISTINGS)
_EXPECTED_IMAGES = sum(_LISTING_IMAGE_COUNTS.values())


def test_seed_demo_data_populates_expected_counts(session: Session) -> None:
    summary = seed_demo_data(session)

    assert summary.dealers == len(_DEALERS)
    assert summary.tracked_models == len(_TRACKED_MODELS)
    assert summary.listings == len(_LISTINGS)
    assert summary.price_snapshots == _EXPECTED_SNAPSHOTS
    assert summary.images == _EXPECTED_IMAGES

    assert _count(session, Dealer) == len(_DEALERS)
    assert _count(session, TrackedModel) == len(_TRACKED_MODELS)
    assert _count(session, CarListing) == len(_LISTINGS)
    assert _count(session, PriceSnapshot) == _EXPECTED_SNAPSHOTS
    assert _count(session, ListingImage) == _EXPECTED_IMAGES


def test_seed_demo_data_writes_image_files(session: Session) -> None:
    seed_demo_data(session)

    images = session.execute(select(ListingImage)).scalars().all()
    assert images  # at least some images were seeded
    # Every ListingImage row's local file exists under the static root, and the
    # files come from bundled assets (network-free seeding).
    for image in images:
        file_path = settings.static_root / image.local_path
        assert file_path.is_file()
        assert file_path.stat().st_size > 0


def test_seed_demo_data_reset_does_not_accumulate_images(session: Session) -> None:
    seed_demo_data(session)
    seed_demo_data(session, reset=True)

    assert _count(session, ListingImage) == _EXPECTED_IMAGES


def test_seed_demo_data_is_idempotent_without_reset(session: Session) -> None:
    seed_demo_data(session)
    second = seed_demo_data(session)

    assert second.dealers == len(_DEALERS)
    assert second.tracked_models == len(_TRACKED_MODELS)
    assert second.listings == len(_LISTINGS)
    assert second.price_snapshots == _EXPECTED_SNAPSHOTS

    # No duplicates were created.
    assert _count(session, Dealer) == len(_DEALERS)
    assert _count(session, TrackedModel) == len(_TRACKED_MODELS)
    assert _count(session, CarListing) == len(_LISTINGS)
    assert _count(session, PriceSnapshot) == _EXPECTED_SNAPSHOTS


def test_seed_demo_data_with_reset_does_not_accumulate(session: Session) -> None:
    seed_demo_data(session)
    summary = seed_demo_data(session, reset=True)

    assert summary.reset is True
    assert summary.dealers == len(_DEALERS)
    assert summary.tracked_models == len(_TRACKED_MODELS)
    assert summary.listings == len(_LISTINGS)
    assert summary.price_snapshots == _EXPECTED_SNAPSHOTS

    assert _count(session, Dealer) == len(_DEALERS)
    assert _count(session, TrackedModel) == len(_TRACKED_MODELS)
    assert _count(session, CarListing) == len(_LISTINGS)
    assert _count(session, PriceSnapshot) == _EXPECTED_SNAPSHOTS


def test_seed_demo_data_listings_belong_to_demo_dealers(session: Session) -> None:
    seed_demo_data(session)

    demo_slugs = {d["scraper_module"] for d in _DEALERS}
    dealers = session.execute(select(Dealer)).scalars().all()
    assert {d.scraper_module for d in dealers} == demo_slugs

    listings = session.execute(select(CarListing)).scalars().all()
    assert all(listing.dealer_id in {d.id for d in dealers} for listing in listings)
    assert all(listing.external_id.startswith("demo-") for listing in listings)


def test_clear_demo_data_removes_everything(session: Session) -> None:
    seed_demo_data(session)
    image_paths = [
        settings.static_root / image.local_path
        for image in session.execute(select(ListingImage)).scalars().all()
    ]

    summary = clear_demo_data(session)

    assert summary.dealers == len(_DEALERS)
    assert summary.tracked_models == len(_TRACKED_MODELS)
    assert summary.listings == len(_LISTINGS)
    assert summary.price_snapshots == _EXPECTED_SNAPSHOTS
    assert summary.images == _EXPECTED_IMAGES

    assert _count(session, Dealer) == 0
    assert _count(session, TrackedModel) == 0
    assert _count(session, CarListing) == 0
    assert _count(session, PriceSnapshot) == 0
    assert _count(session, ListingImage) == 0

    for path in image_paths:
        assert not path.exists()


def test_clear_demo_data_on_empty_db_is_noop(session: Session) -> None:
    summary = clear_demo_data(session)

    assert summary == ClearSummary(
        dealers=0, tracked_models=0, listings=0, price_snapshots=0, images=0
    )
    assert _count(session, Dealer) == 0
    assert _count(session, TrackedModel) == 0


def test_seed_demo_data_price_history_is_chronological(session: Session) -> None:
    seed_demo_data(session)

    listings = session.execute(select(CarListing)).scalars().all()
    for listing in listings:
        snapshots = (
            session.execute(
                select(PriceSnapshot)
                .where(PriceSnapshot.listing_id == listing.id)
                .order_by(PriceSnapshot.scraped_at)
            )
            .scalars()
            .all()
        )
        timestamps = [s.scraped_at for s in snapshots]
        assert timestamps == sorted(timestamps)
        # The most recent snapshot's price matches the listing's current price.
        assert snapshots[-1].price == listing.price
