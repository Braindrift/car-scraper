"""Tests for `services.tracked_models`.

Covers create/list/delete of `TrackedModel` rows against a seeded temporary
SQLite database, following the pattern in `tests/services/test_listings.py`.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import TrackedModel
from carscraper.db.session import Base, create_db_engine
from carscraper.services.tracked_models import (
    create_tracked_model,
    delete_tracked_model,
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
