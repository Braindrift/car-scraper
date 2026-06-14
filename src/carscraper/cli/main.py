"""Typer CLI entrypoint.

`run-scrape` and friends are implemented once `scrapers/` and `services/`
have real logic (later tickets). For now this just exposes a working `app`
so `carscraper` is a valid console script.
"""

from __future__ import annotations

import typer

app = typer.Typer(help="CarScraper 2.0 command-line interface.")


@app.command()
def run_scrape(
    dealer: str | None = typer.Option(None, help="Limit the run to one dealer slug."),
) -> None:
    """Run a scrape across all enabled dealers (or a single dealer)."""
    if dealer:
        typer.echo(f"run-scrape: dealer={dealer} (not yet implemented)")
    else:
        typer.echo("run-scrape: all dealers (not yet implemented)")


if __name__ == "__main__":
    app()
