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
        year=2018,
        mileage=85_000,
        price=price,
        active=active,
    )
    session.add(listing)
    session.commit()
    return listing


def test_stats_page_empty_state(db_session: Session) -> None:
    response = client.get("/stats")

    assert response.status_code == 200
    assert "No active listings with a price yet" in response.text


def test_stats_page_with_rows(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/stats")

    assert response.status_code == 200
    assert "Volvo" in response.text
    assert "V70" in response.text
    assert "189 000 kr" in response.text
    assert "No active listings with a price yet" not in response.text


def test_stats_page_excludes_listings_without_price(db_session: Session) -> None:
    _seed_listing(db_session, price=None)

    response = client.get("/stats")

    assert response.status_code == 200
    assert "No active listings with a price yet" in response.text


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
