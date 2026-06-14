"""Tests for the dashboard route (`GET /`).

Covers CAR-5's Definition of Done: the route renders the base layout
extended by the empty-state dashboard, and includes the Tailwind/HTMX/
Chart.js script tags.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from carscraper.db.session import Base, SessionLocal, create_db_engine
from carscraper.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def db_session(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    """Point the app at an empty temp DB so the empty-state assertions hold.

    Without this the tests would query the developer's real `carscraper.db`,
    whose contents (e.g. after `seed-demo-data`) would break the empty state.
    """
    db_path = tmp_path / "web_dashboard_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    with Session(engine) as session:
        yield session

    engine.dispose()


def test_dashboard_returns_200_with_empty_state() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "No listings yet — run a scrape to get started." in response.text


def test_dashboard_includes_frontend_dependencies() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "cdn.tailwindcss.com" in response.text
    assert "htmx.org" in response.text
    assert "chart.js" in response.text.lower()
