"""Tests for the tracked-models config page (CAR-7).

Covers:
- `GET /tracked-models` rendering the empty state with zero `TrackedModel`
  rows, and a populated list once rows exist.
- `POST /tracked-models` (the HTMX add form) creating a row and re-rendering
  the list partial, including basic make/model-required validation.
- `DELETE /tracked-models/{id}` (the HTMX remove button) deleting a row and
  re-rendering the list partial.

The app's module-level `SessionLocal` is repointed at a temporary SQLite
database per test, following the pattern in `tests/web/test_listings.py`.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.db.models import TrackedModel
from carscraper.db.session import Base, SessionLocal, create_db_engine
from carscraper.main import app

client = TestClient(app)


@pytest.fixture
def db_session(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    db_path = tmp_path / "web_tracked_models_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    with Session(engine) as session:
        yield session

    engine.dispose()


def _seed_tracked_model(session: Session) -> TrackedModel:
    tracked = TrackedModel(make="Volvo", model="V70", variant="T5")
    session.add(tracked)
    session.commit()
    return tracked


def test_tracked_models_page_empty_state(db_session: Session) -> None:
    response = client.get("/tracked-models")

    assert response.status_code == 200
    assert "No tracked models yet" in response.text
    assert "tracked-models-form" in response.text


def test_tracked_models_page_with_rows(db_session: Session) -> None:
    _seed_tracked_model(db_session)

    response = client.get("/tracked-models")

    assert response.status_code == 200
    assert "Volvo" in response.text
    assert "V70" in response.text
    assert "T5" in response.text
    assert "No tracked models yet" not in response.text


def test_tracked_models_page_in_nav(db_session: Session) -> None:
    response = client.get("/tracked-models")

    assert response.status_code == 200
    assert '<a href="/tracked-models"' in response.text


def test_add_tracked_model_creates_row(db_session: Session) -> None:
    response = client.post(
        "/tracked-models",
        data={"make": "Volvo", "model": "V70", "variant": "T5"},
    )

    assert response.status_code == 200
    assert "Volvo" in response.text
    assert "V70" in response.text
    assert "T5" in response.text
    # Partial response only, no surrounding page chrome.
    assert "<nav" not in response.text

    rows = list(db_session.execute(select(TrackedModel)).scalars().all())
    assert len(rows) == 1
    assert rows[0].make == "Volvo"
    assert rows[0].model == "V70"
    assert rows[0].variant == "T5"


def test_add_tracked_model_without_variant(db_session: Session) -> None:
    response = client.post(
        "/tracked-models",
        data={"make": "Toyota", "model": "Corolla"},
    )

    assert response.status_code == 200
    assert "Toyota" in response.text
    assert "Corolla" in response.text


def test_add_tracked_model_missing_make_shows_error(db_session: Session) -> None:
    response = client.post(
        "/tracked-models",
        data={"make": "", "model": "V70"},
    )

    assert response.status_code == 200
    assert "Make and model are required." in response.text
    assert "No tracked models yet" in response.text


def test_add_tracked_model_missing_model_shows_error(db_session: Session) -> None:
    response = client.post(
        "/tracked-models",
        data={"make": "Volvo", "model": ""},
    )

    assert response.status_code == 200
    assert "Make and model are required." in response.text


def test_add_tracked_model_blank_fields_does_not_create_row(db_session: Session) -> None:
    client.post("/tracked-models", data={"make": "  ", "model": "  "})

    rows = list(db_session.execute(select(TrackedModel)).scalars().all())
    assert rows == []


def test_remove_tracked_model(db_session: Session) -> None:
    tracked = _seed_tracked_model(db_session)

    response = client.delete(f"/tracked-models/{tracked.id}")

    assert response.status_code == 200
    assert "Volvo" not in response.text
    assert "No tracked models yet" in response.text

    rows = list(db_session.execute(select(TrackedModel)).scalars().all())
    assert rows == []


def test_remove_tracked_model_not_found(db_session: Session) -> None:
    response = client.delete("/tracked-models/999")

    assert response.status_code == 200
    assert "No tracked models yet" in response.text


def test_add_then_remove_round_trip(db_session: Session) -> None:
    add_response = client.post(
        "/tracked-models",
        data={"make": "Kia", "model": "Sportage"},
    )
    assert "Kia" in add_response.text

    rows = list(db_session.execute(select(TrackedModel)).scalars().all())
    assert len(rows) == 1
    tracked_id = rows[0].id

    remove_response = client.delete(f"/tracked-models/{tracked_id}")
    assert "Kia" not in remove_response.text
    assert "No tracked models yet" in remove_response.text
