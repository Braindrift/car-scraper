"""Tests for the listings table on the dashboard (CAR-6).

Covers:
- `GET /` rendering the empty state with zero `CarListing` rows, and a
  populated table once rows exist.
- `GET /listings/table` (the HTMX partial target) rendering the same table
  for both empty and populated cases, and respecting filter query params.

The app's module-level `SessionLocal` is repointed at a temporary SQLite
database per test, following the pattern in `tests/db/test_session.py`.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer, ListingImage
from carscraper.db.session import Base, SessionLocal, create_db_engine
from carscraper.main import app

client = TestClient(app)


@pytest.fixture
def db_session(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    db_path = tmp_path / "web_listings_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    with Session(engine) as session:
        yield session

    engine.dispose()


def _seed_listing(session: Session) -> CarListing:
    dealer = Dealer(
        name="Bilia Stockholm", base_url="https://bilia.example", scraper_module="bilia"
    )
    session.add(dealer)
    session.commit()

    listing = CarListing(
        dealer_id=dealer.id,
        external_id="1",
        url="https://bilia.example/1",
        make="Volvo",
        model="V70",
        variant="T5",
        year=2018,
        mileage=85_000,
        price=189_000,
        active=True,
    )
    session.add(listing)
    session.commit()
    return listing


def _add_images(session: Session, listing: CarListing, count: int) -> None:
    for position in range(count):
        session.add(
            ListingImage(
                listing_id=listing.id,
                local_path=f"images/bilia/{listing.external_id}/{position}.png",
                position=position,
            )
        )
    session.commit()


def test_listing_detail_renders_carousel_with_images(db_session: Session) -> None:
    listing = _seed_listing(db_session)
    _add_images(db_session, listing, 3)

    response = client.get(f"/listings/{listing.id}")

    assert response.status_code == 200
    assert 'id="image-carousel"' in response.text
    # All three images are rendered, in order, served from /static.
    assert "/static/images/bilia/1/0.png" in response.text
    assert "/static/images/bilia/1/1.png" in response.text
    assert "/static/images/bilia/1/2.png" in response.text
    # Multiple images -> prev/next controls and a position indicator.
    assert 'id="carousel-prev"' in response.text
    assert 'id="carousel-next"' in response.text
    assert 'id="carousel-position"' in response.text
    assert "No images available" not in response.text


def test_listing_detail_single_image_has_no_nav(db_session: Session) -> None:
    listing = _seed_listing(db_session)
    _add_images(db_session, listing, 1)

    response = client.get(f"/listings/{listing.id}")

    assert response.status_code == 200
    assert 'id="image-carousel"' in response.text
    assert "/static/images/bilia/1/0.png" in response.text
    # A single image needs no prev/next controls or indicator.
    assert 'id="carousel-prev"' not in response.text
    assert 'id="carousel-next"' not in response.text


def test_listing_detail_renders_placeholder_without_images(db_session: Session) -> None:
    listing = _seed_listing(db_session)

    response = client.get(f"/listings/{listing.id}")

    assert response.status_code == 200
    assert "No images available" in response.text
    assert 'id="image-carousel"' not in response.text
    assert 'id="carousel-next"' not in response.text


def test_dashboard_empty_state(db_session: Session) -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "No listings yet — run a scrape to get started." in response.text
    assert "listings-filter-form" in response.text


def test_dashboard_with_rows(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/")

    assert response.status_code == 200
    assert "Volvo" in response.text
    assert "V70" in response.text
    assert "Bilia Stockholm" in response.text
    assert "No listings yet" not in response.text


def test_listings_table_partial_empty(db_session: Session) -> None:
    response = client.get("/listings/table")

    assert response.status_code == 200
    assert "No listings yet — run a scrape to get started." in response.text
    # The partial doesn't include the surrounding page chrome.
    assert "<nav" not in response.text


def test_listings_table_partial_with_rows(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/listings/table")

    assert response.status_code == 200
    assert "Volvo" in response.text
    assert "V70" in response.text


def test_listings_table_filter_by_make_matches(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/listings/table", params={"make": "Volvo"})

    assert response.status_code == 200
    assert "Volvo" in response.text


def test_listings_table_filter_by_make_no_match(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/listings/table", params={"make": "Toyota"})

    assert response.status_code == 200
    assert "No listings yet — run a scrape to get started." in response.text
    assert "Volvo" not in response.text


def test_listings_table_filter_by_price_range(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/listings/table", params={"min_price": "200000"})

    assert response.status_code == 200
    assert "Volvo" not in response.text


def test_listings_table_active_only(db_session: Session) -> None:
    listing = _seed_listing(db_session)
    listing.active = False
    db_session.commit()

    response = client.get("/listings/table", params={"active_only": "true"})

    assert response.status_code == 200
    assert "Volvo" not in response.text


def test_dashboard_dealer_dropdown_lists_dealers(db_session: Session) -> None:
    _seed_listing(db_session)

    response = client.get("/")

    assert response.status_code == 200
    assert "Bilia Stockholm" in response.text


def test_dashboard_shows_new_badge_for_unviewed_listing(db_session: Session) -> None:
    _seed_listing(db_session)  # never viewed -> NEW

    response = client.get("/")

    assert response.status_code == 200
    assert "NEW" in response.text


def test_viewing_listing_clears_new_badge(db_session: Session) -> None:
    listing = _seed_listing(db_session)

    # Before viewing: NEW badge shown.
    assert "NEW" in client.get("/").text

    # Viewing the detail page records last_viewed_at.
    detail = client.get(f"/listings/{listing.id}")
    assert detail.status_code == 200

    # On the next dashboard load the badge is gone (status reads SEEN -> date).
    after = client.get("/")
    assert "NEW" not in after.text
    assert "UPDATED" not in after.text
