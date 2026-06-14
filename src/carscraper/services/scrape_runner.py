"""Run scrapers for enabled dealers.

This is the minimal "run all enabled dealer scrapers" entry point the CLI
needs (CAR-4). It mediates between `db` (looking up `Dealer` rows) and
`scrapers.registry` (resolving/running a scraper by `scraper_module` slug).

Persisting the resulting `CarListingDTO`s into `CarListing`/`PriceSnapshot`
rows, deduplication, and marking stale listings inactive are out of scope for
this ticket — see CLAUDE.md's "services mediate" and cross-cutting-logic
notes for where that lands later.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.db.models import Dealer, TrackedModel
from carscraper.scrapers.base import CarListingDTO, TrackedModelSpec
from carscraper.scrapers.registry import run_scraper


@dataclass(frozen=True)
class ScrapeRunResult:
    """Summary of a scrape run across one or more dealers."""

    dealers_scraped: int
    listings: list[CarListingDTO] = field(default_factory=list)


async def run_enabled_dealers(session: Session, dealer_slug: str | None = None) -> ScrapeRunResult:
    """Run the scraper for each enabled `Dealer`, optionally limited to one slug.

    With zero matching `Dealer` rows (e.g. an empty database, or a
    `dealer_slug` that doesn't match any enabled dealer), this returns a
    `ScrapeRunResult` with `dealers_scraped == 0` rather than raising.
    """

    stmt = select(Dealer).where(Dealer.enabled.is_(True))
    if dealer_slug is not None:
        stmt = stmt.where(Dealer.scraper_module == dealer_slug)

    dealers = session.execute(stmt).scalars().all()

    tracked = [
        TrackedModelSpec(make=tm.make, model=tm.model, variant=tm.variant)
        for tm in session.execute(select(TrackedModel)).scalars()
    ]

    listings: list[CarListingDTO] = []
    for dealer in dealers:
        listings.extend(await run_scraper(dealer.scraper_module, tracked))

    return ScrapeRunResult(dealers_scraped=len(dealers), listings=listings)
