"""CLI tests for `clear-demo-data` (CAR-17).

Exercises the Typer command via `CliRunner` against a temporary, file-based
SQLite database, following the pattern in `tests/cli/test_seed_demo_data.py`.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from carscraper.cli.main import app
from carscraper.config import settings
from carscraper.db.models import CarListing, Dealer, PriceSnapshot, TrackedModel
from carscraper.db.session import Base, SessionLocal, create_db_engine
from carscraper.services.demo_data import _DEALERS, _LISTINGS

runner = CliRunner()

_EXPECTED_SNAPSHOTS = sum(len(listing["price_history"]) for listing in _LISTINGS)


def _count(engine, model: type) -> int:
    with Session(engine) as session:
        return session.execute(select(func.count()).select_from(model)).scalar_one()


def test_clear_demo_data_removes_seeded_rows(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli_clear_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})
    monkeypatch.setattr(settings, "static_root", tmp_path / "static")

    seed_result = runner.invoke(app, ["seed-demo-data"])
    clear_result = runner.invoke(app, ["clear-demo-data"])

    assert seed_result.exit_code == 0
    assert clear_result.exit_code == 0
    assert f"{len(_DEALERS)} dealer(s)" in clear_result.output
    assert f"{len(_LISTINGS)} listing(s)" in clear_result.output
    assert f"{_EXPECTED_SNAPSHOTS} price snapshot(s)" in clear_result.output

    assert _count(engine, Dealer) == 0
    assert _count(engine, TrackedModel) == 0
    assert _count(engine, CarListing) == 0
    assert _count(engine, PriceSnapshot) == 0

    engine.dispose()


def test_clear_demo_data_on_empty_db_reports_zero(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli_clear_empty_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})
    monkeypatch.setattr(settings, "static_root", tmp_path / "static")

    result = runner.invoke(app, ["clear-demo-data"])

    assert result.exit_code == 0
    assert "0 dealer(s)" in result.output

    engine.dispose()
