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

from carscraper.db.models import CarListing, Dealer, PriceSnapshot, TrackedModel
from carscraper.db.session import Base, create_db_engine
from carscraper.services.demo_data import _DEALERS, _LISTINGS, _TRACKED_MODELS, seed_demo_data


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    db_path = tmp_path / "demo_data_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def _count(session: Session, model: type) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


_EXPECTED_SNAPSHOTS = sum(len(listing["price_history"]) for listing in _LISTINGS)


def test_seed_demo_data_populates_expected_counts(session: Session) -> None:
    summary = seed_demo_data(session)

    assert summary.dealers == len(_DEALERS)
    assert summary.tracked_models == len(_TRACKED_MODELS)
    assert summary.listings == len(_LISTINGS)
    assert summary.price_snapshots == _EXPECTED_SNAPSHOTS

    assert _count(session, Dealer) == len(_DEALERS)
    assert _count(session, TrackedModel) == len(_TRACKED_MODELS)
    assert _count(session, CarListing) == len(_LISTINGS)
    assert _count(session, PriceSnapshot) == _EXPECTED_SNAPSHOTS


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
