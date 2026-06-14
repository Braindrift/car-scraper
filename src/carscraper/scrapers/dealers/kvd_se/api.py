"""HTTP fetching for kvd.se's public auction-search JSON API (CAR-16).

kvd.se is a Swedish car-auction marketplace that exposes a public, unauthenticated
JSON API at `API_URL`. It paginates via `limit`/`offset` and returns a page's
listings under `data["auctions"]`.

This module's only job is fetching pages and accumulating their `auctions`
entries into a flat list of raw dicts — no parsing into `CarListingDTO` (that's
`parse.py`) and no filtering by tracked make/model (that's `services/`, per
CLAUDE.md).
"""

from __future__ import annotations

import httpx

API_URL = "https://api.kvd.se/v1/auction/search"

# Number of listings requested per page. Matches the page size kvd.se's own
# frontend uses.
_PAGE_SIZE = 20

# Safety cap on the number of pages fetched in a single run, in case the API
# ever stops returning an empty `auctions` page (e.g. due to an off-by-one or
# a transient bug) — without this, a bug could turn into an unbounded loop.
# ~700 car listings / 20 per page is ~35 pages, so 100 leaves generous headroom.
_MAX_PAGES = 100

_TIMEOUT = 10


async def fetch_car_auctions(client: httpx.AsyncClient) -> list[dict]:
    """Fetch every page of the `vehicleType=car` auction search results.

    Pages are requested in order (`offset=0, 20, 40, ...`) until a page
    returns an empty `auctions` list or `_MAX_PAGES` pages have been fetched.
    Returns the concatenation of every page's raw `auctions` entries (each a
    `dict`, not yet normalized into a `CarListingDTO`).
    """
    auctions: list[dict] = []

    for page in range(_MAX_PAGES):
        offset = page * _PAGE_SIZE
        response = await client.get(
            API_URL,
            params={
                "vehicleType": "car",
                "orderBy": "-grade",
                "limit": _PAGE_SIZE,
                "offset": offset,
            },
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()

        page_auctions = data.get("auctions") or []
        if not page_auctions:
            break

        auctions.extend(page_auctions)

    return auctions
