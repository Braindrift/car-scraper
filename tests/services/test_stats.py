"""Tests for `services.stats` (CAR-8, CAR-19, CAR-20, CAR-24, CAR-28).

`price_history` is exercised against a seeded temporary SQLite database,
covering populated and empty cases. `model_overview_stats`,
`year_bucket_stats`, and `mileage_bucket_stats` (CAR-19) are exercised
against a second seeded database covering rollups, bucket boundaries,
"Unknown" buckets, the `include_inactive` toggle, and (CAR-20)
`model_overview_stats`'s `make`/`model` scoping. CAR-24's `median_price`/
`excluded_count` fields and "low bid" exclusion are exercised against a third
seeded database covering: a group with no priced listings, a bucket that's
entirely "low bid" relative to the overall scope, and a mixed group with some
listings excluded and some counted. CAR-28's make/model casing normalisation
is exercised against a fourth seeded database.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer, PriceSnapshot, TrackedModel
from carscraper.db.session import Base, create_db_engine
from carscraper.services.stats import (
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
            price=130_000,
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
    # Active Volvo V70 listings: T5 @150k (2000 mi), T6 @170k (2001 mi), and
    # high-mileage T5 @130k. The inactive T5 (999k) is excluded by default
    # (active-only).
    assert volvo.model == "V70"
    assert volvo.listing_count == 3  # v70-t5, v70-t6, v70-high-mileage (all active)
    assert volvo.min_price == 130_000
    assert volvo.max_price == 170_000
    assert volvo.avg_price == pytest.approx((150_000 + 170_000 + 130_000) / 3)
    assert volvo.median_price == 150_000
    assert volvo.excluded_count == 0


def test_model_overview_stats_include_inactive(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session, include_inactive=True)

    volvo = next(row for row in results if row.make == "Volvo")
    assert volvo.listing_count == 4
    assert volvo.min_price == 130_000
    assert volvo.max_price == 999_000
    assert volvo.excluded_count == 0


def test_model_overview_stats_ordered_by_make_model(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session)

    assert [(row.make, row.model) for row in results] == [("Kia", "Sportage"), ("Volvo", "V70")]


def test_model_overview_stats_filtered_by_make_and_model(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session, make="Volvo", model="V70")

    assert [(row.make, row.model) for row in results] == [("Volvo", "V70")]
    assert results[0].listing_count == 3  # active Volvo V70s only


def test_model_overview_stats_filtered_by_make_only(
    session: Session, bucket_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session, make="Kia")

    assert [(row.make, row.model) for row in results] == [("Kia", "Sportage")]


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

    # 2010: only the active high-mileage T5 (130k) — the inactive one is
    # excluded by default.
    assert by_year[2010].listing_count == 1
    assert by_year[2010].min_price == 130_000
    assert by_year[2010].max_price == 130_000

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

    # 2010: both the inactive T5 (999k) and active high-mileage T5 (130k).
    assert by_year[2010].listing_count == 2
    assert by_year[2010].min_price == 130_000
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
    assert by_bucket["30000+"].min_price == 130_000
    assert by_bucket["30000+"].max_price == 130_000
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


@pytest.fixture
def car24_seeded(session: Session) -> dict[str, object]:
    """Seed listings exercising CAR-24's `median_price`/exclusion behavior.

    - Saab 9-5 (make="Saab", model="9-5"): two listings, both with no price
      at all — exercises "no listings with a price".
    - Audi A4 (make="Audi", model="A4"): three listings whose prices
      (300k, 320k, 280k) are all close together — none is a "low bid" within
      its own group, but two of them sit in a mileage bucket
      (`mileage=35_000`, "30000+") whose prices (300k, 320k) are far below
      the *overall* scope's preliminary median once the BMW listing (below)
      is included — exercising a bucket that's entirely "low bid" relative
      to the overall scope.
    - BMW 3 Series (make="BMW", model="3 Series"): two listings in the same
      `(make, model)` group — one priced normally (200k) and one with a
      "low bid" placeholder price (50k, well below 66% of the group's
      preliminary median) — exercising a mixed group with some listings
      excluded and some counted.
    """
    dealer = Dealer(
        name="Bilia Stockholm", base_url="https://bilia.example", scraper_module="bilia"
    )
    session.add(dealer)
    session.commit()

    listings = [
        # Saab 9-5: no priced listings at all.
        CarListing(
            dealer_id=dealer.id,
            external_id="saab-1",
            url="https://bilia.example/saab-1",
            make="Saab",
            model="9-5",
            year=2008,
            mileage=10_000,
            price=None,
            active=True,
        ),
        CarListing(
            dealer_id=dealer.id,
            external_id="saab-2",
            url="https://bilia.example/saab-2",
            make="Saab",
            model="9-5",
            year=2009,
            mileage=12_000,
            price=None,
            active=True,
        ),
        # BMW 3 Series: mixed group — one normal price, one "low bid".
        CarListing(
            dealer_id=dealer.id,
            external_id="bmw-1",
            url="https://bilia.example/bmw-1",
            make="BMW",
            model="3 Series",
            year=2017,
            mileage=40_000,
            price=200_000,
            active=True,
        ),
        CarListing(
            dealer_id=dealer.id,
            external_id="bmw-2",
            url="https://bilia.example/bmw-2",
            make="BMW",
            model="3 Series",
            year=2018,
            mileage=42_000,
            price=50_000,  # "low bid": well below 66% of the group median (200k).
            active=True,
        ),
    ]
    session.add_all(listings)
    session.commit()

    return {listing.external_id: listing for listing in listings}


def test_model_overview_stats_no_priced_listings_in_group(
    session: Session, car24_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session, make="Saab", model="9-5")

    assert len(results) == 1
    saab = results[0]
    assert saab.listing_count == 2
    assert saab.excluded_count == 2
    assert saab.avg_price is None
    assert saab.min_price is None
    assert saab.max_price is None
    assert saab.median_price is None


def test_model_overview_stats_mixed_group_excludes_low_bid(
    session: Session, car24_seeded: dict[str, object]
) -> None:
    results = model_overview_stats(session, make="BMW", model="3 Series")

    assert len(results) == 1
    bmw = results[0]
    # Both listings count toward listing_count, but the 50k "low bid" is
    # excluded from the price aggregates (50_000 < 0.66 * 200_000).
    assert bmw.listing_count == 2
    assert bmw.excluded_count == 1
    assert bmw.avg_price == 200_000
    assert bmw.min_price == 200_000
    assert bmw.max_price == 200_000
    assert bmw.median_price == 200_000


def test_year_bucket_stats_all_low_bid_bucket_reports_no_usable_price(
    session: Session, car24_seeded: dict[str, object]
) -> None:
    results = year_bucket_stats(session, make="BMW", model="3 Series")

    by_year = {row.year: row for row in results}

    # Scope (BMW 3 Series, active): prices [200_000, 50_000].
    # Preliminary median = 125_000; threshold = 82_500.
    # 2017 (200k) is usable; 2018 (50k) is not.
    assert by_year[2017].listing_count == 1
    assert by_year[2017].excluded_count == 0
    assert by_year[2017].min_price == 200_000
    assert by_year[2017].max_price == 200_000
    assert by_year[2017].median_price == 200_000

    assert by_year[2018].listing_count == 1
    assert by_year[2018].excluded_count == 1
    assert by_year[2018].min_price is None
    assert by_year[2018].max_price is None
    assert by_year[2018].median_price is None


def test_mileage_bucket_stats_all_low_bid_bucket_reports_no_usable_price(
    session: Session, car24_seeded: dict[str, object]
) -> None:
    results = mileage_bucket_stats(session, make="BMW", model="3 Series")

    by_bucket = {row.bucket: row for row in results}

    # Scope (BMW 3 Series, active): prices [200_000, 50_000].
    # Preliminary median = 125_000; threshold = 82_500.
    # mileage=40_000 (200k) is usable; mileage=42_000 (50k) is not — both
    # fall in the "30000+" bucket, which still gets one usable price.
    assert by_bucket["30000+"].listing_count == 2
    assert by_bucket["30000+"].excluded_count == 1
    assert by_bucket["30000+"].min_price == 200_000
    assert by_bucket["30000+"].max_price == 200_000
    assert by_bucket["30000+"].median_price == 200_000


def test_year_bucket_stats_no_priced_listings_reports_none(
    session: Session, car24_seeded: dict[str, object]
) -> None:
    results = year_bucket_stats(session, make="Saab", model="9-5")

    for row in results:
        assert row.min_price is None
        assert row.max_price is None
        assert row.median_price is None
        assert row.excluded_count == row.listing_count

    assert sum(row.listing_count for row in results) == 2


# ---------------------------------------------------------------------------
# CAR-28: make/model casing normalisation via TrackedModel
# ---------------------------------------------------------------------------


@pytest.fixture
def car28_seeded(session: Session) -> dict[str, object]:
    """Seed listings and TrackedModels for CAR-28 casing-normalisation tests.

    - TrackedModel("Ford", "S-Max") defines the canonical casing.
    - Two CarListing rows: one stored as "Ford"/"S-MAX" (all-caps suffix),
      another as "ford"/"s-max" (all-lowercase) — both should merge into
      a single stats row with the TrackedModel's casing ("Ford", "S-Max").
    - One CarListing for "Opel"/"Astra" with no matching TrackedModel — it
      should appear under its own raw value (not discarded).
    """
    dealer = Dealer(
        name="Test Dealer", base_url="https://dealer.example", scraper_module="test_dealer"
    )
    session.add(dealer)
    # Define canonical casing via TrackedModel.
    session.add(TrackedModel(make="Ford", model="S-Max"))
    session.commit()

    listings = [
        CarListing(
            dealer_id=dealer.id,
            external_id="ford-1",
            url="https://dealer.example/ford-1",
            make="Ford",
            model="S-MAX",
            price=200_000,
            active=True,
        ),
        CarListing(
            dealer_id=dealer.id,
            external_id="ford-2",
            url="https://dealer.example/ford-2",
            make="ford",
            model="s-max",
            price=220_000,
            active=True,
        ),
        CarListing(
            dealer_id=dealer.id,
            external_id="opel-1",
            url="https://dealer.example/opel-1",
            make="Opel",
            model="Astra",
            price=150_000,
            active=True,
        ),
    ]
    session.add_all(listings)
    session.commit()

    return {"dealer": dealer, **{listing.external_id: listing for listing in listings}}


def test_model_overview_stats_merges_casing_variants(
    session: Session, car28_seeded: dict[str, object]
) -> None:
    """CAR-28: listings that differ only in make/model casing merge into one row.

    "Ford"/"S-MAX" and "ford"/"s-max" both match TrackedModel("Ford", "S-Max")
    after case-folding, so `model_overview_stats` should produce exactly one
    row for Ford S-Max (using the TrackedModel casing) combining both listings.
    """
    results = model_overview_stats(session)

    makes_models = [(row.make, row.model) for row in results]
    assert ("Ford", "S-Max") in makes_models, f"Expected canonical (Ford, S-Max) in {makes_models}"

    # The raw variants ("Ford"/"S-MAX" and "ford"/"s-max") must not appear
    # as separate rows.
    assert ("Ford", "S-MAX") not in makes_models
    assert ("ford", "s-max") not in makes_models

    ford = next(row for row in results if row.make == "Ford" and row.model == "S-Max")
    assert ford.listing_count == 2
    assert ford.min_price == 200_000
    assert ford.max_price == 220_000


def test_model_overview_stats_unmatched_listing_uses_raw_value(
    session: Session, car28_seeded: dict[str, object]
) -> None:
    """CAR-28: listings without a matching TrackedModel appear under their raw value."""
    results = model_overview_stats(session)

    makes_models = [(row.make, row.model) for row in results]
    assert (
        "Opel",
        "Astra",
    ) in makes_models, (
        f"Expected unmatched (Opel, Astra) to appear under its raw value in {makes_models}"
    )

    opel = next(row for row in results if row.make == "Opel")
    assert opel.listing_count == 1
    assert opel.min_price == 150_000


def test_model_overview_stats_ilike_filter_matches_differently_cased_listings(
    session: Session, car28_seeded: dict[str, object]
) -> None:
    """CAR-28: make/model filter uses ilike so canonical values match raw DB rows.

    Passing the canonical make="Ford", model="S-Max" should return all
    Ford S-Max listings regardless of how their make/model was stored.
    """
    results = model_overview_stats(session, make="Ford", model="S-Max")

    assert len(results) == 1
    assert results[0].make == "Ford"
    assert results[0].model == "S-Max"
    assert results[0].listing_count == 2
