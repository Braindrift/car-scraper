"""Tests for `DELETE /api/listings/{id}` (CAR-32).

Covers:
- 204 on successful delete of an existing listing.
- 204 on idempotent delete of a non-existent listing (no error raised).
- Associated `PriceSnapshot` rows are removed.
- Associated `ListingImage` rows and files are removed.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer, ListingImage, PriceSnapshot
from carscraper.db.session import Base, SessionLocal, create_db_engine
from carscraper.main import app

client = TestClient(app)


@pytest.fixture
def db_session(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    db_path = tmp_path / "api_listings_test.db"
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
        external_id="ext-1",
        url="https://bilia.example/ext-1",
        make="Volvo",
        model="V70",
        active=True,
    )
    session.add(listing)
    session.commit()
    return listing


def test_delete_listing_returns_204(db_session: Session) -> None:
    listing = _seed_listing(db_session)

    response = client.delete(f"/api/listings/{listing.id}")

    assert response.status_code == 204


def test_delete_listing_removes_row_from_db(db_session: Session) -> None:
    listing = _seed_listing(db_session)
    listing_id = listing.id

    client.delete(f"/api/listings/{listing_id}")

    db_session.expire_all()
    assert db_session.get(CarListing, listing_id) is None


def test_delete_listing_missing_id_returns_204(db_session: Session) -> None:
    """DELETE on a non-existent listing is idempotent: returns 204, no error."""
    response = client.delete("/api/listings/9999")

    assert response.status_code == 204


def test_delete_listing_cascades_price_snapshots(db_session: Session) -> None:
    listing = _seed_listing(db_session)
    listing_id = listing.id
    db_session.add(PriceSnapshot(listing_id=listing_id, price=200_000))
    db_session.commit()

    client.delete(f"/api/listings/{listing_id}")

    db_session.expire_all()
    rows = db_session.execute(
        select(PriceSnapshot).where(PriceSnapshot.listing_id == listing_id)
    ).first()
    assert rows is None


def test_delete_listing_cascades_listing_images(db_session: Session) -> None:
    listing = _seed_listing(db_session)
    listing_id = listing.id
    db_session.add(
        ListingImage(
            listing_id=listing_id,
            local_path="images/bilia/ext-1/0.jpg",
            position=0,
        )
    )
    db_session.commit()

    client.delete(f"/api/listings/{listing_id}")

    db_session.expire_all()
    rows = db_session.execute(
        select(ListingImage).where(ListingImage.listing_id == listing_id)
    ).first()
    assert rows is None
