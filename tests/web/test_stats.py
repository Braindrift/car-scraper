"""Tests for the stats summary view and listing detail view (CAR-8, CAR-20).

Covers:
- `GET /stats` rendering the empty state with no active/priced listings, and
  a populated per-(make, model) overview table (variants rolled up) once
  rows exist.
- `?make=&model=` scoping the overview table to a single tracked model, and
  the "All models" link clearing that scope.
- The "Include inactive listings" `include_inactive` toggle changing which
  listings contribute to the overview.
- `GET /listings/{id}` rendering listing details plus a Chart.js
  price-history chart (chart container + data present), the empty-history
  state, and a 404 for a nonexistent listing.

The app's module-level `SessionLocal` is repointed at a temporary SQLite
database per test, following the pattern in `tests/web/test_listings.py`.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer, PriceSnapshot
from carscraper.db.session import Base, SessionLocal, create_db_engine
from carscraper.main import app

client = TestClient(app)


@pytest.fixture
def db_session(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    db_path = tmp_path / "web_stats_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    with Session(engine) as session:
        yield session

    engine.dispose()


def _seed_listing(
    session: Session,
    *,
    external_id: str = "1",
    make: str = "Volvo",
    model: str = "V70",
    variant: str | None = "T5",
    year: int | None = 2018,
    mileage: int | None = 85_000,
    price: int | None = 189_000,
    active: bool = True,
) -> CarListing:
    dealer = session.query(Dealer).filter_by(name="Bilia Stockholm").first()
    if dealer is None:
        dealer = Dealer(
            name="Bilia Stockholm", base_url="https://bilia.example", scraper_module="bilia"
        )
        session.add(dealer)
        session.commit()

    listing = CarListing(
        dealer_id=dealer.id,
        external_id=external_id,
        url=f"https://bilia.example/{external_id}",
        make=make,
        model=model,
        variant=variant,
        year=year,
        mileage=mileage,
        price=price,
        active=active,
    )
    session.add(listing)
    session.commit()
    return listing


def test_stats_page_empty_state(db_session: Session) -> None:
    response = client.get("/stats")

    assert response.status_code == 200
    assert "No active listings yet" in response.text


def test_stats_page_with_rows(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/stats")

    assert response.status_code == 200
    assert "Volvo" in response.text
    assert "V70" in response.text
    assert "189 000 kr" in response.text
    assert "No active listings yet" not in response.text


def test_stats_page_includes_listings_without_price(db_session: Session) -> None:
    """CAR-24: an unpriced listing still appears (counted), with a dash for price."""
    _seed_listing(db_session, price=None)

    response = client.get("/stats")

    assert response.status_code == 200
    assert "No active listings yet" not in response.text
    assert "Volvo" in response.text
    assert "V70" in response.text
    # listing_count is 1, but excluded_count is also 1 (no usable price).
    assert "1 excluded" in response.text


def test_stats_page_rolls_up_variants(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", variant="T5", price=150_000)
    _seed_listing(db_session, external_id="2", variant="T6", price=170_000)

    response = client.get("/stats")

    assert response.status_code == 200
    # One congregated row for Volvo V70 (both variants rolled up).
    assert response.text.count('<td class="py-2 pr-4">V70</td>') == 1
    # Avg of 150k/170k = 160k, with min/max shown as the price range.
    assert "160 000 kr" in response.text
    assert "150 000" in response.text
    assert "170 000" in response.text


def test_stats_page_scoped_by_make_and_model(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", make="Volvo", model="V70", price=150_000)
    _seed_listing(db_session, external_id="2", make="Kia", model="Sportage", price=220_000)

    response = client.get("/stats", params={"make": "Volvo", "model": "V70"})

    assert response.status_code == 200
    assert "V70" in response.text
    assert "Sportage" not in response.text
    # "All models" reset link is present when scoped.
    assert "All models" in response.text


def test_stats_page_all_models_link_absent_when_unscoped(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/stats")

    assert response.status_code == 200
    assert "All models combined" in response.text
    assert ">All models<" not in response.text


def test_stats_page_include_inactive_toggles_counts(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", price=150_000, active=True)
    _seed_listing(db_session, external_id="2", price=999_000, active=False)

    active_only = client.get("/stats")
    assert active_only.status_code == 200
    assert "1" in active_only.text  # listing_count == 1
    assert "999 000" not in active_only.text

    with_inactive = client.get("/stats", params={"include_inactive": "true"})
    assert with_inactive.status_code == 200
    assert "999 000" in with_inactive.text


def test_stats_page_distribution_charts_render(db_session: Session) -> None:
    _seed_listing(db_session, year=2018, mileage=5_000, price=150_000)

    response = client.get("/stats")

    assert response.status_code == 200
    # Tabbed "By year" / "By mileage" section with both chart canvases.
    assert ">By year<" in response.text
    assert ">By mileage<" in response.text
    assert 'id="year-chart"' in response.text
    assert 'id="mileage-chart"' in response.text


def test_stats_page_year_bucket_chart_data(db_session: Session) -> None:
    # Prices are all within 66% of the scope's preliminary median (150k), so
    # none are treated as "low bid" / excluded.
    _seed_listing(db_session, external_id="1", year=2018, mileage=5_000, price=150_000)
    _seed_listing(db_session, external_id="2", year=2020, mileage=5_000, price=200_000)
    _seed_listing(db_session, external_id="3", year=None, mileage=5_000, price=120_000)

    response = client.get("/stats")

    assert response.status_code == 200
    # Years ascending, "Unknown" bucket last; one entry per bucket.
    assert '"2018", "2020", "Unknown"' in response.text
    # Counts: one listing per bucket.
    assert "[1, 1, 1]" in response.text
    # Price ranges: each bucket has a single listing, so min == max.
    assert "[[150000, 150000], [200000, 200000], [120000, 120000]]" in response.text


def test_stats_page_mileage_bucket_chart_data(db_session: Session) -> None:
    # Prices are all within 66% of the scope's preliminary median (120k), so
    # none are treated as "low bid" / excluded.
    _seed_listing(db_session, external_id="1", year=2018, mileage=1_000, price=150_000)
    _seed_listing(db_session, external_id="2", year=2018, mileage=35_000, price=100_000)
    _seed_listing(db_session, external_id="3", year=2018, mileage=None, price=120_000)

    response = client.get("/stats")

    assert response.status_code == 200
    # Fixed bucket order: only buckets with data are returned, "30000+" before "Unknown".
    assert '"0-2000", "30000+", "Unknown"' in response.text
    assert "[[150000, 150000], [100000, 100000], [120000, 120000]]" in response.text


def test_stats_page_distribution_charts_scoped_by_make_and_model(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", make="Volvo", model="V70", year=2018, price=150_000)
    _seed_listing(
        db_session, external_id="2", make="Kia", model="Sportage", year=2020, price=220_000
    )

    response = client.get("/stats", params={"make": "Volvo", "model": "V70"})

    assert response.status_code == 200
    # Only the Volvo V70's year (2018) appears in the chart data.
    assert '"2018"' in response.text
    assert '"2020"' not in response.text


def test_stats_page_distribution_charts_empty_state(db_session: Session) -> None:
    response = client.get("/stats")

    assert response.status_code == 200
    assert ">By year<" in response.text
    assert ">By mileage<" in response.text
    assert response.text.count("No data to chart yet.") == 2


def test_stats_listings_filters_by_year(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", year=2018, price=150_000)
    _seed_listing(db_session, external_id="2", year=2020, price=200_000)

    response = client.get("/stats/listings", params={"year": "2018"})

    assert response.status_code == 200
    assert "2018" in response.text
    assert "2020" not in response.text
    assert "Year: 2018" in response.text


def test_stats_listings_filters_by_year_unknown(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", year=2018, price=150_000)
    _seed_listing(db_session, external_id="2", year=None, price=80_000)

    response = client.get("/stats/listings", params={"year_unknown": "true"})

    assert response.status_code == 200
    assert "80 000 kr" in response.text
    assert "150 000 kr" not in response.text
    assert "Year: Unknown" in response.text


def test_stats_listings_filters_by_mileage_range(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", mileage=1_000, price=151_000)
    _seed_listing(db_session, external_id="2", mileage=35_000, price=52_000)

    response = client.get("/stats/listings", params={"min_mileage": "0", "max_mileage": "2000"})

    assert response.status_code == 200
    assert "151 000 kr" in response.text
    assert "52 000 kr" not in response.text
    assert "Mileage: 0-2000 km" in response.text


def test_stats_listings_filters_by_mileage_open_ended_bucket(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", mileage=1_000, price=151_000)
    _seed_listing(db_session, external_id="2", mileage=35_000, price=52_000)

    response = client.get("/stats/listings", params={"min_mileage": "30001"})

    assert response.status_code == 200
    assert "52 000 kr" in response.text
    assert "151 000 kr" not in response.text
    assert "Mileage: 30001+ km" in response.text


def test_stats_listings_filters_by_mileage_unknown(db_session: Session) -> None:
    _seed_listing(db_session, external_id="1", mileage=1_000, price=151_000)
    _seed_listing(db_session, external_id="2", mileage=None, price=82_000)

    response = client.get("/stats/listings", params={"mileage_unknown": "true"})

    assert response.status_code == 200
    assert "82 000 kr" in response.text
    assert "151 000 kr" not in response.text
    assert "Mileage: Unknown" in response.text


def test_stats_listings_respects_scope_and_include_inactive(db_session: Session) -> None:
    _seed_listing(
        db_session,
        external_id="1",
        make="Volvo",
        model="V70",
        year=2018,
        price=150_000,
        active=True,
    )
    _seed_listing(
        db_session,
        external_id="2",
        make="Kia",
        model="Sportage",
        year=2018,
        price=220_000,
        active=True,
    )
    _seed_listing(
        db_session,
        external_id="3",
        make="Volvo",
        model="V70",
        year=2018,
        price=999_000,
        active=False,
    )

    scoped = client.get("/stats/listings", params={"make": "Volvo", "model": "V70", "year": "2018"})
    assert scoped.status_code == 200
    assert "150 000 kr" in scoped.text
    assert "220 000 kr" not in scoped.text
    assert "999 000 kr" not in scoped.text

    with_inactive = client.get(
        "/stats/listings",
        params={"make": "Volvo", "model": "V70", "year": "2018", "include_inactive": "true"},
    )
    assert with_inactive.status_code == 200
    assert "999 000 kr" in with_inactive.text


def test_stats_listings_empty_state(db_session: Session) -> None:
    _seed_listing(db_session, year=2018, price=150_000)

    response = client.get("/stats/listings", params={"year": "1999"})

    assert response.status_code == 200
    assert "No listings yet" in response.text


def test_stats_page_charts_have_drilldown_container_and_click_handlers(
    db_session: Session,
) -> None:
    _seed_listing(db_session, year=2018, mileage=5_000, price=150_000)

    response = client.get("/stats")

    assert response.status_code == 200
    assert 'id="stats-drilldown"' in response.text
    assert "onClick" in response.text
    assert "/stats/listings" in response.text


def test_listing_detail_not_found(db_session: Session) -> None:
    response = client.get("/listings/999")

    assert response.status_code == 404


def test_listing_detail_empty_history(db_session: Session) -> None:
    listing = _seed_listing(db_session)

    response = client.get(f"/listings/{listing.id}")

    assert response.status_code == 200
    assert "Volvo" in response.text
    assert "V70" in response.text
    assert "Bilia Stockholm" in response.text
    assert "No price history yet" in response.text
    # No chart canvas when there's no history to plot.
    assert 'id="price-history-chart"' not in response.text


def test_listing_detail_with_history_renders_chart(db_session: Session) -> None:
    listing = _seed_listing(db_session)

    db_session.add_all(
        [
            PriceSnapshot(listing_id=listing.id, price=195_000, scraped_at=datetime(2026, 1, 1)),
            PriceSnapshot(listing_id=listing.id, price=189_000, scraped_at=datetime(2026, 1, 8)),
        ]
    )
    db_session.commit()

    response = client.get(f"/listings/{listing.id}")

    assert response.status_code == 200
    assert 'id="price-history-chart"' in response.text
    # Chart.js data is serialized into the page via `tojson`.
    assert "195000" in response.text
    assert "189000" in response.text
    assert "No price history yet" not in response.text
