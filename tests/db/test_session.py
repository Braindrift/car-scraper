"""Tests for engine/session factory plumbing."""

from __future__ import annotations

from sqlalchemy import inspect

from carscraper.db.models import Dealer
from carscraper.db.session import Base, SessionLocal, create_db_engine, get_session


def test_create_db_engine_sqlite(tmp_path) -> None:
    db_path = tmp_path / "engine_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")

    Base.metadata.create_all(engine)

    inspector = inspect(engine)
    assert "dealers" in inspector.get_table_names()

    engine.dispose()


def test_get_session_context_manager(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "session_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Point the module-level SessionLocal at our temp engine for this test.
    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    with get_session() as session:
        session.add(
            Dealer(
                name="Test Dealer",
                base_url="https://example.com",
                scraper_module="test_dealer",
            )
        )
        session.commit()

        fetched = session.query(Dealer).filter_by(scraper_module="test_dealer").one()
        assert fetched.name == "Test Dealer"

    engine.dispose()
