"""Tests for `services.listings`.

`list_car_listings` is exercised against a seeded temporary SQLite database
covering each supported filter (make, model, dealer, price range,
active-only, year, mileage range) individually and in combination.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer
from carscraper.db.session import Base, create_db_engine
from carscraper.services.listings import (
    ListingFilters,
    list_car_listings,
    list_dealers_with_listings,
    set_listing_discarded,
)


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    db_path = tmp_path / "listings_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


@pytest.fixture
def seeded(session: Session) -> dict[str, object]:
    """Seed two dealers and a small mix of `CarListing` rows."""
    bilia = Dealer(name="Bilia Stockholm", base_url="https://bilia.example", scraper_module="bilia")
    kia_dealer = Dealer(name="Kia Center", base_url="https://kia.example", scraper_module="kia")
    session.add_all([bilia, kia_dealer])
    session.commit()

    volvo_active = CarListing(
        dealer_id=bilia.id,
        external_id="1",
        url="https://bilia.example/1",
        make="Volvo",
        model="V70",
        price=150_000,
        year=2015,
        mileage=5_000,
        active=True,
    )
    volvo_inactive = CarListing(
        dealer_id=bilia.id,
        external_id="2",
        url="https://bilia.example/2",
        make="Volvo",
        model="XC60",
        price=300_000,
        year=2018,
        mileage=10_000,
        active=False,
    )
    kia = CarListing(
        dealer_id=kia_dealer.id,
        external_id="3",
        url="https://kia.example/3",
        make="Kia",
        model="Sportage",
        price=220_000,
        year=None,
        mileage=None,
        active=True,
    )
    session.add_all([volvo_active, volvo_inactive, kia])
    session.commit()

    return {
        "bilia": bilia,
        "kia_dealer": kia_dealer,
        "volvo_active": volvo_active,
        "volvo_inactive": volvo_inactive,
        "kia": kia,
    }


def test_no_filters_returns_all_listings(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session)

    assert len(results) == 3


def test_no_listings_returns_empty_list(session: Session) -> None:
    results = list_car_listings(session)

    assert results == []


def test_filter_by_make(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session, ListingFilters(make="Volvo"))

    assert {listing.id for listing in results} == {
        seeded["volvo_active"].id,
        seeded["volvo_inactive"].id,
    }


def test_filter_by_model(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session, ListingFilters(model="Sportage"))

    assert [listing.id for listing in results] == [seeded["kia"].id]


def test_filter_by_dealer(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session, ListingFilters(dealer_id=seeded["kia_dealer"].id))

    assert [listing.id for listing in results] == [seeded["kia"].id]


def test_filter_by_price_range(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session, ListingFilters(min_price=160_000, max_price=250_000))

    assert [listing.id for listing in results] == [seeded["kia"].id]


def test_filter_by_year(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session, ListingFilters(year=2015))

    assert [listing.id for listing in results] == [seeded["volvo_active"].id]


def test_filter_by_year_excludes_null_year(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session, ListingFilters(year=2020))

    assert results == []


def test_filter_by_mileage_range(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session, ListingFilters(min_mileage=6_000, max_mileage=15_000))

    assert [listing.id for listing in results] == [seeded["volvo_inactive"].id]


def test_filter_by_min_mileage_excludes_null_mileage(
    session: Session, seeded: dict[str, object]
) -> None:
    results = list_car_listings(session, ListingFilters(min_mileage=0))

    assert seeded["kia"].id not in {listing.id for listing in results}


def test_filter_by_mileage_range_inclusive_boundaries(
    session: Session, seeded: dict[str, object]
) -> None:
    results = list_car_listings(session, ListingFilters(min_mileage=5_000, max_mileage=5_000))

    assert [listing.id for listing in results] == [seeded["volvo_active"].id]


def test_filter_active_only(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(session, ListingFilters(active_only=True))

    assert {listing.id for listing in results} == {
        seeded["volvo_active"].id,
        seeded["kia"].id,
    }


def test_combined_filters(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(
        session,
        ListingFilters(make="Volvo", active_only=True),
    )

    assert [listing.id for listing in results] == [seeded["volvo_active"].id]


def test_combined_filters_no_match(session: Session, seeded: dict[str, object]) -> None:
    results = list_car_listings(
        session,
        ListingFilters(make="Volvo", model="Sportage"),
    )

    assert results == []


def test_discarded_filter_excludes_and_isolates(
    session: Session, seeded: dict[str, object]
) -> None:
    set_listing_discarded(session, seeded["kia"].id, discarded=True)

    # discarded=False -> only the non-discarded rows (the main dashboard).
    active_list = list_car_listings(session, ListingFilters(discarded=False))
    assert {listing.id for listing in active_list} == {
        seeded["volvo_active"].id,
        seeded["volvo_inactive"].id,
    }

    # discarded=True -> only the discarded rows (the Discarded page).
    discarded_list = list_car_listings(session, ListingFilters(discarded=True))
    assert [listing.id for listing in discarded_list] == [seeded["kia"].id]

    # No discarded filter still returns everything.
    assert len(list_car_listings(session)) == 3


def test_set_listing_discarded_toggles_and_persists(
    session: Session, seeded: dict[str, object]
) -> None:
    listing_id = seeded["volvo_active"].id

    discarded = set_listing_discarded(session, listing_id, discarded=True)
    assert discarded is not None and discarded.discarded is True

    restored = set_listing_discarded(session, listing_id, discarded=False)
    assert restored is not None and restored.discarded is False


def test_set_listing_discarded_missing_returns_none(session: Session) -> None:
    assert set_listing_discarded(session, 999, discarded=True) is None


def test_list_dealers_with_listings(session: Session, seeded: dict[str, object]) -> None:
    dealers = list_dealers_with_listings(session)

    assert [dealer.name for dealer in dealers] == ["Bilia Stockholm", "Kia Center"]


def test_list_dealers_with_listings_empty(session: Session) -> None:
    dealers = list_dealers_with_listings(session)

    assert dealers == []
