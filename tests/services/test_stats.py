"""Tests for `services.stats` (CAR-8, CAR-19).

`avg_price_per_model` and `price_history` are exercised against a seeded
temporary SQLite database, covering populated and empty cases.
`model_overview_stats`, `year_bucket_stats`, and `mileage_bucket_stats`
(CAR-19) are exercised against a second seeded database covering rollups,
bucket boundaries, "Unknown" buckets, and the `include_inactive` toggle.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer, PriceSnapshot
from carscraper.db.session import Base, create_db_engine
from carscraper.services.stats import (
    avg_price_per_model,
    mileage_bucket_stats,
    model_overview_stats,
    price_history,
    year_bucket_stats,
)


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


@pytest.fixture
def bucket_seeded(session: Session) -> dict[str, object]:
    """Seed listings covering model rollups and mileage/year bucket edges.

    - Two Volvo V70 variants (T5 and T6, both active, priced) to exercise
      `model_overview_stats` rolling variants up into one (make, model) row.
    - An inactive Volvo V70 (priced) to exercise `include_inactive`.
    - A Kia Sportage with no `year`/`mileage` to exercise the "Unknown"
      buckets.
    - Listings sitting exactly on mileage-bucket boundaries (2000/2001,
      30000/30001) to exercise boundary handling.
    """
    dealer = Dealer(
        name="Bilia Stockholm", base_url="https://bilia.example", scraper_module="bilia"
    )
    session.add(dealer)
    session.commit()

    listings = [
        CarListing(
            dealer_id=dealer.id,
            external_id="v70-t5",
            url="https://bilia.example/v70-t5",
            make="Volvo",
            model="V70",
            variant="T5",
            year=2015,
            mileage=2000,
            price=150_000,
            active=True,
        ),
        CarListing(
            dealer_id=dealer.id,
            external_id="v70-t6",
            url="https://bilia.example/v70-t6",
            make="Volvo",
            model="V70",
            variant="T6",
            year=2015,
            mileage=2001,
            price=170_000,
            active=True,
        ),
        CarListing(
            dealer_id=dealer.id,
            external_id="v70-inactive",
            url="https://bilia.example/v70-inactive",
            make="Volvo",
            model="V70",
            variant="T5",
            year=2010,
            mileage=30_000,
            price=999_000,
            active=False,
        ),
        CarListing(
            dealer_id=dealer.id,
            external_id="v70-high-mileage",
            url="https://bilia.example/v70-high-mileage",
            make="Volvo",
            model="V70",
            variant="T5",
            year=2010,
            mileage=30_001,
            price=80_000,
            active=True,
        ),
        CarListing(
            dealer_id=dealer.id,
            external_id="kia-unknown",
            url="https://bilia.example/kia-unknown",
            make="Kia",
            model="Sportage",
            year=None,
            mileage=None,
            price=220_000,
            active=True,
        ),
    ]
    session.add_all(listings)
    session.commit()

    return {listing.external_id: listing for listing in listings}


def test_model_overview_stats_empty(session: Session) -> None:
    assert model_overview_stats(session) == []


def test_model_overview_stats_rolls_up_variants(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session)

    volvo = next(row for row in results if row.make == "Volvo")
    # Active Volvo V70 listings: T5 @150k (2000 mi) and T6 @170k (2001 mi).
    # The inactive T5 (999k) and high-mileage T5 (80k) are excluded by
    # default (active-only, and high-mileage one is active so it counts).
    assert volvo.model == "V70"
    assert volvo.listing_count == 3  # v70-t5, v70-t6, v70-high-mileage (all active)
    assert volvo.min_price == 80_000
    assert volvo.max_price == 170_000
    assert volvo.avg_price == pytest.approx((150_000 + 170_000 + 80_000) / 3)


def test_model_overview_stats_include_inactive(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session, include_inactive=True)

    volvo = next(row for row in results if row.make == "Volvo")
    assert volvo.listing_count == 4
    assert volvo.min_price == 80_000
    assert volvo.max_price == 999_000


def test_model_overview_stats_ordered_by_make_model(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session)

    assert [(row.make, row.model) for row in results] == [("Kia", "Sportage"), ("Volvo", "V70")]


def test_year_bucket_stats_empty(session: Session) -> None:
    assert year_bucket_stats(session) == []


def test_year_bucket_stats_groups_by_year_with_unknown_bucket(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = year_bucket_stats(session)

    by_year = {row.year: row for row in results}

    # 2015: active T5 (150k, 2000 mi) and T6 (170k, 2001 mi).
    assert by_year[2015].listing_count == 2
    assert by_year[2015].min_price == 150_000
    assert by_year[2015].max_price == 170_000

    # 2010: only the active high-mileage T5 (80k) — the inactive one is
    # excluded by default.
    assert by_year[2010].listing_count == 1
    assert by_year[2010].min_price == 80_000
    assert by_year[2010].max_price == 80_000

    # Unknown (null year): the Kia, priced at 220k.
    assert by_year[None].listing_count == 1
    assert by_year[None].min_price == 220_000
    assert by_year[None].max_price == 220_000

    # Unknown bucket sorts last.
    assert results[-1].year is None


def test_year_bucket_stats_include_inactive(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = year_bucket_stats(session, include_inactive=True)

    by_year = {row.year: row for row in results}

    # 2010: both the inactive T5 (999k) and active high-mileage T5 (80k).
    assert by_year[2010].listing_count == 2
    assert by_year[2010].min_price == 80_000
    assert by_year[2010].max_price == 999_000


def test_year_bucket_stats_filtered_by_make_and_model(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = year_bucket_stats(session, make="Kia", model="Sportage")

    assert [row.year for row in results] == [None]
    assert results[0].listing_count == 1


def test_mileage_bucket_stats_empty(session: Session) -> None:
    assert mileage_bucket_stats(session) == []


def test_mileage_bucket_stats_boundaries_and_unknown(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = mileage_bucket_stats(session)

    by_bucket = {row.bucket: row for row in results}

    # mileage=2000 falls in "0-2000".
    assert by_bucket["0-2000"].listing_count == 1
    assert by_bucket["0-2000"].min_price == 150_000
    assert by_bucket["0-2000"].max_price == 150_000

    # mileage=2001 falls in "2001-5000", not "0-2000".
    assert by_bucket["2001-5000"].listing_count == 1
    assert by_bucket["2001-5000"].min_price == 170_000
    assert by_bucket["2001-5000"].max_price == 170_000

    # mileage=30001 falls in "30000+" (open-ended), not "22001-30000".
    # The inactive mileage=30000 listing is excluded by default.
    assert by_bucket["30000+"].listing_count == 1
    assert by_bucket["30000+"].min_price == 80_000
    assert by_bucket["30000+"].max_price == 80_000
    assert "22001-30000" not in by_bucket

    # Unknown (null mileage): the Kia, priced at 220k.
    assert by_bucket["Unknown"].listing_count == 1
    assert by_bucket["Unknown"].min_price == 220_000
    assert by_bucket["Unknown"].max_price == 220_000

    # Buckets follow MILEAGE_BUCKETS order, with "Unknown" last.
    assert results[-1].bucket == "Unknown"


def test_mileage_bucket_stats_include_inactive_adds_boundary_bucket(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = mileage_bucket_stats(session, include_inactive=True)

    by_bucket = {row.bucket: row for row in results}

    # mileage=30000 (inactive) now falls in "22001-30000".
    assert by_bucket["22001-30000"].listing_count == 1
    assert by_bucket["22001-30000"].min_price == 999_000
    assert by_bucket["22001-30000"].max_price == 999_000


def test_mileage_bucket_stats_filtered_by_make_and_model(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = mileage_bucket_stats(session, make="Volvo", model="V70")

    assert "Unknown" not in {row.bucket for row in results}
    assert sum(row.listing_count for row in results) == 3  # active Volvo V70s only
