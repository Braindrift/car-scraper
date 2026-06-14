"""Typer CLI entrypoint.

Thin wrapper over `services`/`scrapers.registry` (per CLAUDE.md: CLI
entrypoints contain no business logic of their own).
"""

from __future__ import annotations

import asyncio

import typer

from carscraper.db.session import get_session
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


if __name__ == "__main__":
    app()
