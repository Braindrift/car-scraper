"""`BaseScraper` implementation for kvd.se (CAR-16).

kvd.se is a Swedish car-auction marketplace with a public JSON API (see
`api.py`). Per CAR-16's design, this scraper fetches the *entire*
`vehicleType=car` catalog (~700 listings) on each run and returns all of them
as `CarListingDTO`s — it does not know which makes/models the user is tracking.
`services/scrape_results.py::filter_tracked` narrows this down to configured
`TrackedModel`s downstream (per CLAUDE.md, that filtering is a `services/`
concern, not a scraper concern).
"""

from __future__ import annotations

import httpx

from carscraper.scrapers.base import BaseScraper, CarListingDTO, TrackedModelSpec
from carscraper.scrapers.dealers.kvd_se.api import fetch_car_auctions
from carscraper.scrapers.dealers.kvd_se.parse import parse_auction
from carscraper.scrapers.registry import register


@register("kvd_se")
class KvdSeScraper(BaseScraper):
    """Fetches and parses kvd.se's full car-auction catalog."""

    async def scrape(self, tracked: list[TrackedModelSpec] | None = None) -> list[CarListingDTO]:
        # kvd.se's API has no per-make/model filter, so the whole catalog is
        # fetched regardless - `tracked` is ignored (see CAR-16).
        async with httpx.AsyncClient() as client:
            auctions = await fetch_car_auctions(client)

        listings: list[CarListingDTO] = []
        for raw in auctions:
            dto = parse_auction(raw)
            if dto is not None:
                listings.append(dto)

        return listings
