"""`BaseScraper` implementation for bilweb.se (CAR-18).

bilweb.se is a national used-car marketplace aggregator (~73,000 listings,
server-rendered HTML). Its search pages cap at ~30 results with no working
pagination, so unlike kvd_se (CAR-16, which fetches its entire catalog), this
scraper fetches one `/sok/<brand-slug>/<model-slug>` page **per tracked
make/model** (see `api.py::fetch_search_pages`). With no tracked models,
there's nothing to fetch, so `scrape()` returns `[]`.
"""

from __future__ import annotations

import httpx

from carscraper.scrapers.base import BaseScraper, CarListingDTO, TrackedModelSpec
from carscraper.scrapers.dealers.bilweb_se.api import fetch_search_pages
from carscraper.scrapers.dealers.bilweb_se.parse import parse_listing_cards
from carscraper.scrapers.registry import register

_TIMEOUT = 10


@register("bilweb_se")
class BilwebSeScraper(BaseScraper):
    """Fetches and parses bilweb.se search-result pages for tracked models."""

    async def scrape(self, tracked: list[TrackedModelSpec] | None = None) -> list[CarListingDTO]:
        if not tracked:
            return []

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            pages = await fetch_search_pages(client, tracked)

        dtos = [dto for html in pages for dto in parse_listing_cards(html)]

        # Dedupe by external_id - the same listing can appear on more than one
        # tracked make/model's search page (unlikely, but cheap to guard).
        return list({dto.external_id: dto for dto in dtos}.values())
