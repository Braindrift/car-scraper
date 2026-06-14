"""CLI tests for `seed-demo-data` (CAR-9).

Exercises the Typer command via `CliRunner` against a temporary, file-based
SQLite database with the core tables created, following the pattern in
`tests/cli/test_run_scrape.py`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from carscraper.cli.main import app
from carscraper.db.models import CarListing, Dealer, PriceSnapshot, TrackedModel
from carscraper.db.session import Base, SessionLocal, create_db_engine
from carscraper.services.demo_data import _DEALERS, _LISTINGS, _TRACKED_MODELS

runner = CliRunner()

_EXPECTED_SNAPSHOTS = sum(len(listing["price_history"]) for listing in _LISTINGS)


def _count(engine, model: type) -> int:
    with Session(engine) as session:
        return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_seed_demo_data_populates_expected_counts(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli_seed_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    result = runner.invoke(app, ["seed-demo-data"])

    assert result.exit_code == 0
    assert _count(engine, Dealer) == len(_DEALERS)
    assert _count(engine, TrackedModel) == len(_TRACKED_MODELS)
    assert _count(engine, CarListing) == len(_LISTINGS)
    assert _count(engine, PriceSnapshot) == _EXPECTED_SNAPSHOTS

    engine.dispose()


def test_seed_demo_data_rerun_does_not_duplicate(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli_seed_rerun_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    first = runner.invoke(app, ["seed-demo-data"])
    second = runner.invoke(app, ["seed-demo-data"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert _count(engine, Dealer) == len(_DEALERS)
    assert _count(engine, TrackedModel) == len(_TRACKED_MODELS)
    assert _count(engine, CarListing) == len(_LISTINGS)
    assert _count(engine, PriceSnapshot) == _EXPECTED_SNAPSHOTS

    engine.dispose()


def test_seed_demo_data_reset_does_not_accumulate(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli_seed_reset_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    first = runner.invoke(app, ["seed-demo-data"])
    second = runner.invoke(app, ["seed-demo-data", "--reset"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert _count(engine, Dealer) == len(_DEALERS)
    assert _count(engine, TrackedModel) == len(_TRACKED_MODELS)
    assert _count(engine, CarListing) == len(_LISTINGS)
    assert _count(engine, PriceSnapshot) == _EXPECTED_SNAPSHOTS

    engine.dispose()
