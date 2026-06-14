"""Scraper contract: `CarListingDTO` and `BaseScraper`.

`CarListingDTO` is the normalization boundary described in CLAUDE.md: every
scraper, regardless of how messy or dealer-specific the source HTML is,
returns a list of these. Anything dealer-specific stays inside that dealer's
scraper module and is translated to this shape before leaving it.

Field set mirrors the scrape-relevant columns of `CarListing`
(`db/models.py`): identity/specs (`external_id`, `url`, `make`, `model`,
`variant`, `year`, `mileage`, `price`, `fuel_type`, `transmission`).
DB-only/service-managed fields (`id`, `dealer_id`, `first_seen`, `last_seen`,
`active`) are intentionally excluded — those are populated by `services/`
when persisting a DTO, not by the scraper.

`BaseScraper.scrape()` is a single async method returning
`list[CarListingDTO]`, rather than separate `fetch`/`parse` steps. This keeps
the contract small and lets each dealer module decide internally how to split
fetch vs. parse (per CLAUDE.md, a dealer may still be split into
`fetch.py`/`parse.py` if it grows large — `scrape()` is just the public entry
point the registry calls). `async` is required up front because real dealer
scrapers will use Playwright/httpx, both async; a synchronous dummy/test
scraper can simply have a non-`await`-ing async body.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field


class CarListingDTO(BaseModel):
    """Normalized representation of a single car listing from a dealer site.

    Required fields are the minimum needed to identify and place a listing
    (`external_id`, `url`, `make`, `model`). Everything else is optional,
    matching the nullable spec columns on `CarListing` — dealer sites don't
    always expose every attribute.
    """

    model_config = ConfigDict(frozen=True)

    # Stable identifier for this listing on the dealer's site, used together
    # with the dealer to dedupe/upsert during a scrape run.
    external_id: str = Field(min_length=1)
    url: str = Field(min_length=1)

    make: str = Field(min_length=1)
    model: str = Field(min_length=1)
    variant: str | None = None
    year: int | None = None
    mileage: int | None = None
    price: int | None = None
    fuel_type: str | None = None
    transmission: str | None = None


class BaseScraper(ABC):
    """Interface implemented by each dealer's scraper module.

    A scraper's only responsibility is fetching and parsing one dealer's
    listings into `CarListingDTO` objects — no DB access, no business logic
    (see CLAUDE.md's "Layer responsibilities" and "Design Discipline").
    """

    @abstractmethod
    async def scrape(self) -> list[CarListingDTO]:
        """Fetch and parse this dealer's listings into `CarListingDTO`s."""
        raise NotImplementedError
