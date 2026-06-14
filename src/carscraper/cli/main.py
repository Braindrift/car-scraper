"""Typer CLI entrypoint.

Thin wrapper over `services`/`scrapers.registry` (per CLAUDE.md: CLI
entrypoints contain no business logic of their own).
"""

from __future__ import annotations

import asyncio

import typer

from carscraper.db.session import get_session
from carscraper.services.demo_data import clear_demo_data, seed_demo_data
from carscraper.services.scrape_runner import run_enabled_dealers

app = typer.Typer(help="CarScraper 2.0 command-line interface.")


@app.callback()
def main() -> None:
    """CarScraper 2.0 command-line interface.

    An explicit callback keeps Typer in "subcommand" mode even with a single
    command registered, so `run-scrape` must be named explicitly (matching
    `python -m carscraper.cli run-scrape`) rather than Typer collapsing to a
    single default command.
    """


@app.command("run-scrape")
def run_scrape(
    dealer: str | None = typer.Option(None, help="Limit the run to one dealer slug."),
) -> None:
    """Run a scrape across all enabled dealers (or a single dealer).

    With zero dealers configured (or none matching `--dealer`), this
    completes successfully and reports "0 dealers scraped".
    """
    with get_session() as session:
        result = asyncio.run(run_enabled_dealers(session, dealer_slug=dealer))

    typer.echo(
        f"{result.dealers_scraped} dealer(s) scraped, {len(result.listings)} listing(s) found"
    )


@app.command("seed-demo-data")
def seed_demo_data_command(
    reset: bool = typer.Option(
        False,
        "--reset",
        help="Wipe any previously-seeded demo rows before reseeding.",
    ),
) -> None:
    """**Dev/demo-only.** Populate the database with fake dealers, tracked
    models, listings, and price history.

    This exists so the dashboard (listings table, tracked-model config,
    stats, and price-history charts) can be visually checked end to end
    without running a real scraper. It does not touch any real scraped data.

    Without `--reset`, this is idempotent: if demo data already exists, it
    reports the existing counts and makes no further changes. With
    `--reset`, any previously-seeded demo rows are deleted first and the
    database is reseeded from scratch.
    """
    with get_session() as session:
        summary = seed_demo_data(session, reset=reset)

    action = "Reseeded" if summary.reset else "Seeded (or found existing)"
    typer.echo(
        f"{action} demo data: {summary.dealers} dealer(s), "
        f"{summary.tracked_models} tracked model(s), {summary.listings} listing(s), "
        f"{summary.price_snapshots} price snapshot(s), {summary.images} image(s)"
    )


@app.command("clear-demo-data")
def clear_demo_data_command() -> None:
    """**Dev/demo-only.** Remove all demo dealers, tracked models, listings,
    price history, and images seeded by `seed-demo-data`.

    Unlike `seed-demo-data --reset`, this does not reseed afterward — use it
    to get a clean database before testing a real scraper. Safe to run when
    no demo data exists (reports all-zero counts, makes no changes).
    """
    with get_session() as session:
        summary = clear_demo_data(session)

    typer.echo(
        f"Cleared demo data: {summary.dealers} dealer(s), "
        f"{summary.tracked_models} tracked model(s), {summary.listings} listing(s), "
        f"{summary.price_snapshots} price snapshot(s), {summary.images} image(s)"
    )


if __name__ == "__main__":
    app()
