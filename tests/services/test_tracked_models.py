"""Tests for `services.tracked_models`.

Covers create/list/delete of `TrackedModel` rows against a seeded temporary
SQLite database, following the pattern in `tests/services/test_listings.py`.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.db.models import CarListing, Dealer, ListingImage, PriceSnapshot, TrackedModel
from carscraper.db.session import Base, create_db_engine
from carscraper.services.tracked_models import (
    create_tracked_model,
    delete_tracked_model,
    delete_tracked_model_with_data,
    list_tracked_models,
)


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    db_path = tmp_path / "tracked_models_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_list_tracked_models_empty(session: Session) -> None:
    assert list_tracked_models(session) == []


def test_create_tracked_model(session: Session) -> None:
    tracked = create_tracked_model(session, make="Volvo", model="V70", variant="T5")

    assert tracked.id is not None
    assert tracked.make == "Volvo"
    assert tracked.model == "V70"
    assert tracked.variant == "T5"


def test_create_tracked_model_without_variant(session: Session) -> None:
    tracked = create_tracked_model(session, make="Toyota", model="Corolla")

    assert tracked.variant is None


def test_create_tracked_model_blank_variant_stored_as_none(session: Session) -> None:
    tracked = create_tracked_model(session, make="Toyota", model="Corolla", variant="")

    assert tracked.variant is None


def test_list_tracked_models_returns_created_rows(session: Session) -> None:
    create_tracked_model(session, make="Volvo", model="V70", variant="T5")
    create_tracked_model(session, make="Toyota", model="Corolla")

    results = list_tracked_models(session)

    assert {(t.make, t.model, t.variant) for t in results} == {
        ("Volvo", "V70", "T5"),
        ("Toyota", "Corolla", None),
    }


def test_list_tracked_models_ordered_by_make_model_variant(session: Session) -> None:
    create_tracked_model(session, make="Volvo", model="XC60")
    create_tracked_model(session, make="Toyota", model="Corolla")
    create_tracked_model(session, make="Volvo", model="V70")

    results = list_tracked_models(session)

    assert [(t.make, t.model) for t in results] == [
        ("Toyota", "Corolla"),
        ("Volvo", "V70"),
        ("Volvo", "XC60"),
    ]


def test_delete_tracked_model(session: Session) -> None:
    tracked = create_tracked_model(session, make="Volvo", model="V70")

    deleted = delete_tracked_model(session, tracked.id)

    assert deleted is True
    assert list_tracked_models(session) == []


def test_delete_tracked_model_not_found(session: Session) -> None:
    deleted = delete_tracked_model(session, 999)

    assert deleted is False


def test_delete_tracked_model_only_removes_target(session: Session) -> None:
    keep = create_tracked_model(session, make="Toyota", model="Corolla")
    remove = create_tracked_model(session, make="Volvo", model="V70")

    delete_tracked_model(session, remove.id)

    results = list_tracked_models(session)
    assert [t.id for t in results] == [keep.id]


def test_create_tracked_model_persists_across_sessions(tmp_path) -> None:
    db_path = tmp_path / "tracked_models_persist_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        create_tracked_model(session, make="Volvo", model="V70")

    with Session(engine) as session:
        results = list_tracked_models(session)
        assert [(t.make, t.model) for t in results] == [("Volvo", "V70")]

    engine.dispose()


def test_tracked_model_repr(session: Session) -> None:
    tracked = create_tracked_model(session, make="Volvo", model="V70", variant="T5")

    assert repr(tracked) == (
        f"TrackedModel(id={tracked.id!r}, make='Volvo', model='V70', variant='T5')"
    )


def test_tracked_model_is_orm_instance(session: Session) -> None:
    tracked = create_tracked_model(session, make="Volvo", model="V70")

    assert isinstance(tracked, TrackedModel)


# ---------------------------------------------------------------------------
# delete_tracked_model_with_data — cascade tests
# ---------------------------------------------------------------------------


@pytest.fixture
def session_with_dealer(tmp_path) -> Generator[Session, None, None]:
    """Session seeded with a `Dealer` row so listings can reference it."""
    db_path = tmp_path / "tracked_models_cascade_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        dealer = Dealer(
            name="Test Dealer",
            base_url="https://test.example",
            scraper_module="test_dealer",
        )
        session.add(dealer)
        session.commit()
        yield session

    engine.dispose()


def _seed_listing(
    session: Session,
    dealer_id: int,
    make: str,
    model: str,
    external_id: str = "ext-1",
) -> CarListing:
    """Add a `CarListing` row with one `PriceSnapshot`."""
    listing = CarListing(
        dealer_id=dealer_id,
        external_id=external_id,
        url=f"https://test.example/{external_id}",
        make=make,
        model=model,
        active=True,
    )
    session.add(listing)
    session.flush()
    snapshot = PriceSnapshot(listing_id=listing.id, price=100_000)
    session.add(snapshot)
    session.commit()
    return listing


def test_delete_with_data_removes_tracked_model_and_listings(
    session_with_dealer: Session,
) -> None:
    """Cascade delete removes TrackedModel, CarListing, and PriceSnapshot rows."""
    session = session_with_dealer
    dealer_id = session.execute(select(Dealer.id)).scalar_one()

    tracked = create_tracked_model(session, make="Volvo", model="V70")
    listing = _seed_listing(session, dealer_id, make="Volvo", model="V70")

    result = delete_tracked_model_with_data(session, tracked.id)

    assert result is True
    assert session.get(TrackedModel, tracked.id) is None
    assert session.get(CarListing, listing.id) is None
    assert (
        session.execute(select(PriceSnapshot).where(PriceSnapshot.listing_id == listing.id)).first()
        is None
    )


def test_delete_with_data_returns_false_for_missing_id(
    session_with_dealer: Session,
) -> None:
    result = delete_tracked_model_with_data(session_with_dealer, 9999)

    assert result is False


def test_delete_with_data_does_not_remove_other_make_listings(
    session_with_dealer: Session,
) -> None:
    """Listings for a different make/model are left untouched."""
    session = session_with_dealer
    dealer_id = session.execute(select(Dealer.id)).scalar_one()

    tracked = create_tracked_model(session, make="Volvo", model="V70")
    # This listing matches — should be deleted.
    volvo = _seed_listing(session, dealer_id, make="Volvo", model="V70", external_id="v70-1")
    # This listing does not match — should survive.
    kia = _seed_listing(session, dealer_id, make="Kia", model="Sportage", external_id="kia-1")

    delete_tracked_model_with_data(session, tracked.id)

    assert session.get(CarListing, volvo.id) is None
    assert session.get(CarListing, kia.id) is not None


def test_delete_with_data_case_insensitive_make_model(
    session_with_dealer: Session,
) -> None:
    """Match is case-insensitive: 'volvo'/'v70' listing is removed for 'Volvo'/'V70' model."""
    session = session_with_dealer
    dealer_id = session.execute(select(Dealer.id)).scalar_one()

    tracked = create_tracked_model(session, make="Volvo", model="V70")
    # Listing stored with lower-case make/model (as scrapers may produce).
    listing = _seed_listing(session, dealer_id, make="volvo", model="v70")

    delete_tracked_model_with_data(session, tracked.id)

    assert session.get(CarListing, listing.id) is None


def test_delete_with_data_removes_listing_image_rows(
    tmp_path,
    session_with_dealer: Session,
) -> None:
    """ListingImage rows (and their files) are removed by the cascade delete."""
    session = session_with_dealer
    dealer_id = session.execute(select(Dealer.id)).scalar_one()

    tracked = create_tracked_model(session, make="Volvo", model="V70")
    listing = _seed_listing(session, dealer_id, make="Volvo", model="V70")

    # Create a real image file so the service has something to unlink.
    static_root = tmp_path / "static"
    img_dir = static_root / "images" / "test_dealer" / listing.external_id
    img_dir.mkdir(parents=True)
    img_file = img_dir / "0.jpg"
    img_file.write_bytes(b"fake")

    img_row = ListingImage(
        listing_id=listing.id,
        local_path=f"images/test_dealer/{listing.external_id}/0.jpg",
        position=0,
    )
    session.add(img_row)
    session.commit()

    delete_tracked_model_with_data(session, tracked.id, static_root=static_root)

    assert not img_file.exists()
    assert (
        session.execute(select(ListingImage).where(ListingImage.listing_id == listing.id)).first()
        is None
    )
