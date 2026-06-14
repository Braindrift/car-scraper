"""Round-trip create/query tests for the core ORM models.

Each model is exercised against a temporary, file-based SQLite database
created fresh per test via `Base.metadata.create_all`.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer, PriceSnapshot, TrackedModel
from carscraper.db.session import Base, create_db_engine


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    """A `Session` bound to a fresh temporary SQLite database file."""
    db_path = tmp_path / "test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_dealer_round_trip(session: Session) -> None:
    dealer = Dealer(
        name="Bilia Stockholm",
        base_url="https://www.bilia.se/stockholm",
        scraper_module="bilia_stockholm",
    )
    session.add(dealer)
    session.commit()

    fetched = session.query(Dealer).filter_by(scraper_module="bilia_stockholm").one()
    assert fetched.id is not None
    assert fetched.name == "Bilia Stockholm"
    assert fetched.base_url == "https://www.bilia.se/stockholm"
    assert fetched.enabled is True


def test_tracked_model_round_trip(session: Session) -> None:
    tracked = TrackedModel(make="Volvo", model="V70", variant="T5")
    session.add(tracked)
    session.commit()

    fetched = session.query(TrackedModel).filter_by(make="Volvo", model="V70").one()
    assert fetched.id is not None
    assert fetched.variant == "T5"


def test_tracked_model_variant_is_optional(session: Session) -> None:
    tracked = TrackedModel(make="Toyota", model="Corolla")
    session.add(tracked)
    session.commit()

    fetched = session.query(TrackedModel).filter_by(make="Toyota", model="Corolla").one()
    assert fetched.variant is None


def test_car_listing_round_trip(session: Session) -> None:
    dealer = Dealer(
        name="Bilia Stockholm",
        base_url="https://www.bilia.se/stockholm",
        scraper_module="bilia_stockholm",
    )
    session.add(dealer)
    session.commit()

    listing = CarListing(
        dealer_id=dealer.id,
        external_id="12345",
        url="https://www.bilia.se/stockholm/listing/12345",
        make="Volvo",
        model="V70",
        variant="T5",
        year=2018,
        mileage=85000,
        price=189000,
        fuel_type="Petrol",
        transmission="Automatic",
    )
    session.add(listing)
    session.commit()

    fetched = session.query(CarListing).filter_by(dealer_id=dealer.id, external_id="12345").one()
    assert fetched.id is not None
    assert fetched.make == "Volvo"
    assert fetched.model == "V70"
    assert fetched.price == 189000
    assert fetched.active is True
    assert isinstance(fetched.first_seen, datetime)
    assert isinstance(fetched.last_seen, datetime)
    assert fetched.dealer.scraper_module == "bilia_stockholm"


def test_price_snapshot_round_trip(session: Session) -> None:
    dealer = Dealer(
        name="Bilia Stockholm",
        base_url="https://www.bilia.se/stockholm",
        scraper_module="bilia_stockholm",
    )
    session.add(dealer)
    session.commit()

    listing = CarListing(
        dealer_id=dealer.id,
        external_id="12345",
        url="https://www.bilia.se/stockholm/listing/12345",
        make="Volvo",
        model="V70",
        price=189000,
    )
    session.add(listing)
    session.commit()

    snapshot = PriceSnapshot(listing_id=listing.id, price=189000)
    session.add(snapshot)
    session.commit()

    fetched = session.query(PriceSnapshot).filter_by(listing_id=listing.id).one()
    assert fetched.id is not None
    assert fetched.price == 189000
    assert isinstance(fetched.scraped_at, datetime)
    assert fetched.listing.external_id == "12345"

    # Price history: listing -> snapshots relationship.
    assert listing.price_snapshots == [fetched]


def test_car_listing_natural_key_uniqueness(session: Session) -> None:
    dealer = Dealer(
        name="Bilia Stockholm",
        base_url="https://www.bilia.se/stockholm",
        scraper_module="bilia_stockholm",
    )
    session.add(dealer)
    session.commit()

    session.add(
        CarListing(
            dealer_id=dealer.id,
            external_id="dup",
            url="https://example.com/dup",
            make="Volvo",
            model="V70",
        )
    )
    session.commit()

    session.add(
        CarListing(
            dealer_id=dealer.id,
            external_id="dup",
            url="https://example.com/dup-again",
            make="Volvo",
            model="V70",
        )
    )

    with pytest.raises(Exception):  # noqa: B017 - IntegrityError from SQLAlchemy
        session.commit()
