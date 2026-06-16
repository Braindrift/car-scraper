"""`BaseScraper` implementation for bytbil.se (CAR-26).

bytbil.se is a national used-car marketplace (~81k listings, server-rendered
HTML).  Search results are filtered to a hardcoded set of southern Swedish
counties (see ``api.py::_SOUTHERN_REGIONS``) and paginated up to
``_MAX_PAGES = 50`` pages per make/model (see ``api.py``).

``httpx`` is sufficient — no Playwright needed (the site is server-rendered).

With no tracked models, there's nothing to fetch, so ``scrape()`` returns
``[]``.
"""

from __future__ import annotations

import httpx

from carscraper.scrapers.base import BaseScraper, CarListingDTO, TrackedModelSpec, is_leasing_dto
from carscraper.scrapers.dealers.bytbil_se.api import fetch_search_pages
from carscraper.scrapers.dealers.bytbil_se.parse import parse_listing_cards
from carscraper.scrapers.registry import register

_TIMEOUT = 15


@register("bytbil_se")
class BytbilSeScraper(BaseScraper):
    """Fetches and parses bytbil.se search-result pages for tracked models."""

    async def scrape(self, tracked: list[TrackedModelSpec] | None = None) -> list[CarListingDTO]:
        if not tracked:
            return []

        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            pages = await fetch_search_pages(client, tracked)

        dtos = [
            dto for html, make, model in pages for dto in parse_listing_cards(html, make, model)
        ]

        # Dedupe by external_id — the same listing could theoretically appear
        # across pages if bytbil.se's pagination overlaps (uncommon but cheap
        # to guard against).
        deduped = list({dto.external_id: dto for dto in dtos}.values())

        # Discard leasing offers — only for-sale listings are of interest (CAR-30).
        return [dto for dto in deduped if not is_leasing_dto(dto)]
