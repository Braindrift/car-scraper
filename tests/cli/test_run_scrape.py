"""CLI tests for `run-scrape`.

Exercises the Typer command via `CliRunner` against a temporary, file-based
SQLite database with the core tables created but zero `Dealer` rows — the
"zero dealers configured" case from CAR-4's Definition of Done.
"""

from __future__ import annotations

from typer.testing import CliRunner

from carscraper.cli.main import app
from carscraper.db.session import Base, SessionLocal, create_db_engine

runner = CliRunner()


def test_run_scrape_with_zero_dealers_exits_zero(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    result = runner.invoke(app, ["run-scrape"])

    assert result.exit_code == 0
    assert "0 dealer(s) scraped" in result.stdout

    engine.dispose()


def test_run_scrape_with_dealer_filter_and_zero_matches_exits_zero(tmp_path, monkeypatch) -> None:
    db_path = tmp_path / "cli_test_filtered.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    result = runner.invoke(app, ["run-scrape", "--dealer", "does-not-exist"])

    assert result.exit_code == 0
    assert "0 dealer(s) scraped" in result.stdout

    engine.dispose()
