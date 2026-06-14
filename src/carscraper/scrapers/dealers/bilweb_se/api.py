"""HTTP fetching for bilweb.se's per-make/model search pages (CAR-18).

bilweb.se is a national used-car marketplace aggregator (~73,000 listings,
server-rendered HTML). Its search pages (`/sok/<brand-slug>/<model-slug>`) cap
at ~30 results with no working pagination, so unlike kvd_se (CAR-16, which
fetches its entire catalog), this module fetches one page **per tracked
make/model** instead.

This module's only job is building URLs and fetching raw HTML — no parsing
into `CarListingDTO` (that's `parse.py`) and no business logic about which
makes/models are tracked (that's `services/`, the caller already filtered to
`TrackedModelSpec`s).
"""

from __future__ import annotations

import logging

import httpx

from carscraper.scrapers.base import TrackedModelSpec
from carscraper.scrapers.dealers.bilweb_se.parse import parse_listing_cards

logger = logging.getLogger(__name__)

BASE_URL = "https://bilweb.se"

_TIMEOUT = 10


def _slug(value: str) -> str:
    """Lowercase `value` and replace spaces with hyphens for a URL slug.

    E.g. "Mercedes-Benz" -> "mercedes-benz" (bilweb.se 301-redirects this to
    "mercedes" - handled by `follow_redirects=True` on the client).
    """
    return value.strip().lower().replace(" ", "-")


async def fetch_search_pages(
    client: httpx.AsyncClient, tracked: list[TrackedModelSpec]
) -> list[str]:
    """Fetch one `/sok/<brand-slug>/<model-slug>` page per unique (make, model).

    `(make, model)` pairs are deduped case-insensitively before fetching, so
    multiple `TrackedModelSpec`s for the same make/model (e.g. differing only
    by `variant`) result in a single request.

    Returns the raw HTML of each page that responds 200 and contains at least
    one listing card. Pages that respond non-200, or 200 with zero cards, are
    logged and skipped rather than treated as fatal - this is the expected
    outcome for a make/model slug bilweb doesn't (currently) have any
    listings for, or a slug mismatch.
    """
    seen: set[tuple[str, str]] = set()
    pages: list[str] = []

    for spec in tracked:
        key = (spec.make.casefold(), spec.model.casefold())
        if key in seen:
            continue
        seen.add(key)

        url = f"{BASE_URL}/sok/{_slug(spec.make)}/{_slug(spec.model)}"
        try:
            response = await client.get(url, timeout=_TIMEOUT)
        except httpx.HTTPError as exc:
            logger.warning("Skipping bilweb.se search page %s: request failed: %s", url, exc)
            continue

        if response.status_code != 200:
            logger.warning(
                "Skipping bilweb.se search page %s: unexpected status %s",
                url,
                response.status_code,
            )
            continue

        html = response.text
        if not parse_listing_cards(html):
            logger.warning("Skipping bilweb.se search page %s: no listing cards found", url)
            continue

        pages.append(html)

    return pages
