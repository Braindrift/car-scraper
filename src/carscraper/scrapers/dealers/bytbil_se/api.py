"""HTTP fetching for bytbil.se search pages with pagination (CAR-26).

bytbil.se is a national used-car marketplace (~81k listings, server-rendered
HTML).  Search results are scoped to a configurable set of ``Regions`` URL
parameters.  This module hardcodes the five southernmost Swedish counties as
``_SOUTHERN_REGIONS`` — the tool is always operated from Lund, so region
filtering is a built-in scraper concern, not app config.

Pagination:
- URL: ``GET /bil?Makes=<Make>&Models=<Model>&Regions=<Region>&...&Page=N``
- 24 results per page, 1-based ``Page=N``.
- Normal termination when HTTP 404 is returned for an out-of-range page, or
  when the page contains no ``li.result-list-item`` cards.
- ``_MAX_PAGES = 50`` safety cap (1,200 listings per make/model per region set).

This module's only job is building URLs and fetching raw HTML — no parsing
into ``CarListingDTO`` (that's ``parse.py``) and no business logic about which
makes/models are tracked (that's ``services/``).
"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import httpx

from carscraper.scrapers.base import TrackedModelSpec
from carscraper.scrapers.dealers.bytbil_se.parse import parse_listing_cards

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bytbil.com"

_MAX_PAGES = 50

# The five southernmost Swedish counties; these are bytbil.se's exact
# "Regions" select values.  Every search URL includes all five so that
# listings across the region are captured in a single paginated run.
_SOUTHERN_REGIONS = (
    "Skåne län",
    "Hallands län",
    "Blekinge län",
    "Kronobergs län",
    "Jönköpings län",
)

_TIMEOUT = 15


def _build_url(make: str, model: str, page: int) -> str:
    """Build a bytbil.se search URL for one make/model and all southern regions.

    ``Regions`` is a repeated parameter — ``urlencode`` with ``doseq=True``
    emits ``&Regions=Sk%C3%A5ne+l%C3%A4n&Regions=Hallands+l%C3%A4n&...``
    which is exactly what bytbil.se expects.
    """
    params: list[tuple[str, str]] = [
        ("Makes", make),
        ("Models", model),
    ]
    for region in _SOUTHERN_REGIONS:
        params.append(("Regions", region))
    params.append(("Page", str(page)))
    return f"{BASE_URL}/bil?{urlencode(params)}"


async def fetch_search_pages(
    client: httpx.AsyncClient,
    tracked: list[TrackedModelSpec],
) -> list[tuple[str, str, str]]:
    """Fetch all search pages for each unique (make, model) in ``tracked``.

    Returns a list of ``(html, make, model)`` triples — one per successfully
    fetched page that contains at least one listing card.  The make/model
    strings are passed back so ``scraper.py`` can forward them to
    ``parse_listing_cards``.

    Pagination per (make, model):
    - Pages are fetched sequentially starting at ``Page=1``.
    - Stops on HTTP 404, zero listing cards, or ``_MAX_PAGES`` reached.
    - HTTP errors other than 404 are logged and treated as end-of-pagination
      for that make/model (not fatal).

    ``(make, model)`` pairs are deduped case-insensitively before fetching.
    """
    seen: set[tuple[str, str]] = set()
    pages: list[tuple[str, str, str]] = []

    for spec in tracked:
        key = (spec.make.casefold(), spec.model.casefold())
        if key in seen:
            continue
        seen.add(key)

        make, model = spec.make, spec.model

        for page_num in range(1, _MAX_PAGES + 1):
            url = _build_url(make, model, page_num)
            try:
                response = await client.get(url, timeout=_TIMEOUT)
            except httpx.HTTPError as exc:
                logger.warning(
                    "bytbil.se: request failed for %s page %d: %s",
                    f"{make} {model}",
                    page_num,
                    exc,
                )
                break

            if response.status_code == 404:
                logger.debug(
                    "bytbil.se: 404 on %s page %d — end of results",
                    f"{make} {model}",
                    page_num,
                )
                break

            if response.status_code != 200:
                logger.warning(
                    "bytbil.se: unexpected status %d for %s page %d",
                    response.status_code,
                    f"{make} {model}",
                    page_num,
                )
                break

            html = response.text
            if not parse_listing_cards(html, make, model):
                logger.debug(
                    "bytbil.se: no listing cards on %s page %d — end of results",
                    f"{make} {model}",
                    page_num,
                )
                break

            pages.append((html, make, model))

    return pages
