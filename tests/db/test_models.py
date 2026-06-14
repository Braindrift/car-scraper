"""Round-trip create/query tests for the core ORM models.

Each model is exercised against a temporary, file-based SQLite database
created fresh per test via `Base.metadata.create_all`.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import (
    CarListing,
    Dealer,
    PriceSnapshot,
    ScrapeLogEntry,
    ScrapeRun,
    TrackedModel,
)
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


def _make_dealer(session: Session) -> Dealer:
    dealer = Dealer(
        name="Bilia Stockholm",
        base_url="https://www.bilia.se/stockholm",
        scraper_module="bilia_stockholm",
    )
    session.add(dealer)
    session.commit()
    return dealer


def test_dealer_last_scraped_at_defaults_to_none(session: Session) -> None:
    dealer = _make_dealer(session)

    fetched = session.query(Dealer).filter_by(id=dealer.id).one()
    assert fetched.last_scraped_at is None

    fetched.last_scraped_at = datetime(2026, 6, 14, 12, 0, 0)
    session.commit()

    refetched = session.query(Dealer).filter_by(id=dealer.id).one()
    assert refetched.last_scraped_at == datetime(2026, 6, 14, 12, 0, 0)


def test_scrape_run_round_trip(session: Session) -> None:
    dealer = _make_dealer(session)

    run = ScrapeRun(
        dealer_id=dealer.id,
        status="running",
        new_count=2,
        updated_count=1,
        removed_count=0,
        unchanged_count=5,
    )
    session.add(run)
    session.commit()

    fetched = session.query(ScrapeRun).filter_by(dealer_id=dealer.id).one()
    assert fetched.id is not None
    assert fetched.status == "running"
    assert isinstance(fetched.started_at, datetime)
    assert fetched.finished_at is None
    assert fetched.error_message is None
    assert fetched.new_count == 2
    assert fetched.updated_count == 1
    assert fetched.removed_count == 0
    assert fetched.unchanged_count == 5

    # Relationship: run -> dealer and dealer -> runs.
    assert fetched.dealer.scraper_module == "bilia_stockholm"
    assert dealer.scrape_runs == [fetched]


def test_scrape_run_count_defaults_are_zero(session: Session) -> None:
    dealer = _make_dealer(session)

    run = ScrapeRun(dealer_id=dealer.id, status="running")
    session.add(run)
    session.commit()

    fetched = session.query(ScrapeRun).filter_by(id=run.id).one()
    assert fetched.new_count == 0
    assert fetched.updated_count == 0
    assert fetched.removed_count == 0
    assert fetched.unchanged_count == 0


def test_scrape_log_entry_round_trip(session: Session) -> None:
    dealer = _make_dealer(session)

    listing = CarListing(
        dealer_id=dealer.id,
        external_id="12345",
        url="https://www.bilia.se/stockholm/listing/12345",
        make="Volvo",
        model="V70",
        price=189000,
    )
    session.add(listing)
    run = ScrapeRun(dealer_id=dealer.id, status="success")
    session.add(run)
    session.commit()

    entry = ScrapeLogEntry(
        scrape_run_id=run.id,
        listing_id=listing.id,
        change_type="updated",
        old_price=189000,
        new_price=179000,
    )
    session.add(entry)
    session.commit()

    fetched = session.query(ScrapeLogEntry).filter_by(scrape_run_id=run.id).one()
    assert fetched.id is not None
    assert fetched.change_type == "updated"
    assert fetched.old_price == 189000
    assert fetched.new_price == 179000

    # Relationships in both directions.
    assert fetched.scrape_run.status == "success"
    assert fetched.listing.external_id == "12345"
    assert run.log_entries == [fetched]
    assert listing.scrape_log_entries == [fetched]


def test_scrape_log_entry_prices_are_optional(session: Session) -> None:
    dealer = _make_dealer(session)

    listing = CarListing(
        dealer_id=dealer.id,
        external_id="12345",
        url="https://www.bilia.se/stockholm/listing/12345",
        make="Volvo",
        model="V70",
    )
    session.add(listing)
    run = ScrapeRun(dealer_id=dealer.id, status="success")
    session.add(run)
    session.commit()

    entry = ScrapeLogEntry(
        scrape_run_id=run.id,
        listing_id=listing.id,
        change_type="new",
    )
    session.add(entry)
    session.commit()

    fetched = session.query(ScrapeLogEntry).filter_by(id=entry.id).one()
    assert fetched.old_price is None
    assert fetched.new_price is None
