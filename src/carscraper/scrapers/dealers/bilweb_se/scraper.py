"""`BaseScraper` implementation for bilweb.se (CAR-18).

bilweb.se is a national used-car marketplace aggregator (~73,000 listings,
server-rendered HTML). Its search pages cap at ~30 results with no working
pagination, so unlike kvd_se (CAR-16, which fetches its entire catalog), this
scraper fetches one `/sok/<brand-slug>/<model-slug>` page **per tracked
make/model** (see `api.py::fetch_search_pages`). With no tracked models,
there's nothing to fetch, so `scrape()` returns `[]`.

CAR-27: after parsing and deduplication, listings outside the five southernmost
Swedish counties are discarded. bilweb.se has no server-side region filter, so
we filter client-side on the county slug embedded in each listing URL.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

from carscraper.scrapers.base import BaseScraper, CarListingDTO, TrackedModelSpec
from carscraper.scrapers.dealers.bilweb_se.api import fetch_search_pages
from carscraper.scrapers.dealers.bilweb_se.parse import parse_listing_cards
from carscraper.scrapers.registry import register

_TIMEOUT = 10
_log = logging.getLogger(__name__)

# The five southernmost Swedish counties we care about, encoded as the first
# path segment of each bilweb.se listing URL (CAR-27).
_SOUTHERN_REGION_SLUGS: frozenset[str] = frozenset(
    {
        "skane-lan",
        "hallands-lan",
        "blekinge-lan",
        "kronobergs-lan",
        "jonkopings-lan",
    }
)


def _is_southern(url: str) -> bool:
    """Return True if *url* belongs to a southern Swedish county.

    Parses the first path segment of the URL and checks it against
    ``_SOUTHERN_REGION_SLUGS``.  If the URL cannot be parsed or has no
    path segment, the listing is kept (fail-open) so we never silently
    drop valid data on unexpected URL formats.
    """
    try:
        path = urlparse(url).path
        segment = path.strip("/").split("/")[0]
    except Exception:
        _log.debug("bilweb_se: could not parse county slug from URL %r — keeping (fail-open)", url)
        return True

    if not segment:
        _log.debug("bilweb_se: URL %r has no county path segment — keeping (fail-open)", url)
        return True

    return segment in _SOUTHERN_REGION_SLUGS


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
        deduped = list({dto.external_id: dto for dto in dtos}.values())

        # Discard listings outside the southern-Sweden region (CAR-27).
        return [dto for dto in deduped if _is_southern(dto.url)]
