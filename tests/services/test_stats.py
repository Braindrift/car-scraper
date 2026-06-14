"""Tests for `services.stats` (CAR-8).

`avg_price_per_model` and `price_history` are exercised against a seeded
temporary SQLite database, covering populated and empty cases.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer, PriceSnapshot
from carscraper.db.session import Base, create_db_engine
from carscraper.services.stats import avg_price_per_model, price_history


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    db_path = tmp_path / "stats_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


@pytest.fixture
def seeded(session: Session) -> dict[str, object]:
    """Seed a dealer and a mix of `CarListing` rows.

    Includes active/inactive listings and listings with/without a price.
    """
    dealer = Dealer(
        name="Bilia Stockholm", base_url="https://bilia.example", scraper_module="bilia"
    )
    session.add(dealer)
    session.commit()

    volvo_1 = CarListing(
        dealer_id=dealer.id,
        external_id="1",
        url="https://bilia.example/1",
        make="Volvo",
        model="V70",
        variant="T5",
        price=150_000,
        active=True,
    )
    volvo_2 = CarListing(
        dealer_id=dealer.id,
        external_id="2",
        url="https://bilia.example/2",
        make="Volvo",
        model="V70",
        variant="T5",
        price=170_000,
        active=True,
    )
    volvo_inactive = CarListing(
        dealer_id=dealer.id,
        external_id="3",
        url="https://bilia.example/3",
        make="Volvo",
        model="V70",
        variant="T5",
        price=999_000,
        active=False,
    )
    kia_no_price = CarListing(
        dealer_id=dealer.id,
        external_id="4",
        url="https://bilia.example/4",
        make="Kia",
        model="Sportage",
        price=None,
        active=True,
    )
    session.add_all([volvo_1, volvo_2, volvo_inactive, kia_no_price])
    session.commit()

    return {
        "dealer": dealer,
        "volvo_1": volvo_1,
        "volvo_2": volvo_2,
        "volvo_inactive": volvo_inactive,
        "kia_no_price": kia_no_price,
    }


def test_avg_price_per_model_empty(session: Session) -> None:
    assert avg_price_per_model(session) == []


def test_avg_price_per_model_averages_active_listings_with_price(
    session: Session, seeded: dict[str, object]
) -> None:
    results = avg_price_per_model(session)

    # Only the two active Volvo V70 T5 listings (with a price) contribute;
    # the inactive one and the price-less Kia are excluded.
    assert len(results) == 1
    row = results[0]
    assert row.make == "Volvo"
    assert row.model == "V70"
    assert row.variant == "T5"
    assert row.avg_price == pytest.approx(160_000)
    assert row.listing_count == 2


def test_avg_price_per_model_excludes_listings_without_price(
    session: Session, seeded: dict[str, object]
) -> None:
    results = avg_price_per_model(session)

    assert all(row.make != "Kia" for row in results)


def test_price_history_empty(session: Session, seeded: dict[str, object]) -> None:
    listing = seeded["volvo_1"]
    assert price_history(session, listing.id) == []


def test_price_history_nonexistent_listing(session: Session) -> None:
    assert price_history(session, 9999) == []


def test_price_history_returns_points_oldest_first(
    session: Session, seeded: dict[str, object]
) -> None:
    listing = seeded["volvo_1"]
    now = datetime(2026, 1, 1, 12, 0, 0)

    session.add_all(
        [
            PriceSnapshot(listing_id=listing.id, price=160_000, scraped_at=now),
            PriceSnapshot(listing_id=listing.id, price=150_000, scraped_at=now - timedelta(days=1)),
            PriceSnapshot(
                listing_id=listing.id, price=155_000, scraped_at=now - timedelta(hours=12)
            ),
        ]
    )
    session.commit()

    points = price_history(session, listing.id)

    assert [p.price for p in points] == [150_000, 155_000, 160_000]
    assert points[0].scraped_at < points[1].scraped_at < points[2].scraped_at
