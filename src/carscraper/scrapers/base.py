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

import re
from abc import ABC, abstractmethod

from pydantic import BaseModel, ConfigDict, Field

# Leasing-indicator patterns checked (case-insensitively) against
# `CarListingDTO.raw_price_text` and `CarListingDTO.variant` by
# `is_leasing_dto`. Per CAR-30, these cover the most common signals found on
# Swedish dealer sites; extend the tuple as real data reveals more patterns.
_LEASING_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"kr/mån",  # "kr/mån"
        r"kr/man",  # ASCII fallback for encoding mishaps
        r"per månad",  # "per månad"
        r"per manad",  # ASCII fallback
        r"leasing",
    )
)


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
    # Odometer reading in Swedish mil (1 mil = 10 km) - the unit Swedish
    # dealer sites natively report mileage in.
    mileage: int | None = None
    price: int | None = None
    fuel_type: str | None = None
    transmission: str | None = None

    # Raw price text from the dealer's site, before stripping to a numeric
    # `price`. Populated by parse modules so that `is_leasing_dto` can detect
    # leasing indicators (e.g. "2 450 kr/mån") that are lost once the text is
    # reduced to an integer. `None` when no price element was found on the
    # page.
    raw_price_text: str | None = None

    # Remote image URLs from the dealer's site, in display order. Populated by
    # real dealer scrapers (step 3); `services/images.py` downloads these to
    # local static storage when a listing is persisted. Empty by default —
    # a listing with no images is valid (renders a placeholder in the UI).
    image_urls: list[str] = Field(default_factory=list)


def is_leasing_dto(dto: CarListingDTO) -> bool:
    """Return True if *dto* represents a leasing offer rather than a for-sale listing.

    Checks both `raw_price_text` and `variant` for known leasing keywords
    (see `_LEASING_PATTERNS`). Scrapers call this before appending a DTO to
    their result list and discard any that match (CAR-30).

    Detection is deliberately conservative — a false positive (excluding a
    real for-sale listing) is worse than a false negative (keeping a leasing
    listing), so only clear leasing signals are matched.
    """
    candidates: list[str] = []
    if dto.raw_price_text is not None:
        candidates.append(dto.raw_price_text)
    if dto.variant is not None:
        candidates.append(dto.variant)

    return any(pattern.search(text) for pattern in _LEASING_PATTERNS for text in candidates)


class TrackedModelSpec(BaseModel):
    """Make/model (optionally variant) a scraper should fetch listings for.

    Decoupled from the SQLAlchemy `TrackedModel` (`db/models.py`) so that
    `scrapers/` never imports `db/` (per CLAUDE.md's layer boundaries) —
    `services/` converts `TrackedModel` rows to these before calling
    `BaseScraper.scrape()`.
    """

    model_config = ConfigDict(frozen=True)

    make: str = Field(min_length=1)
    model: str = Field(min_length=1)
    variant: str | None = None


class BaseScraper(ABC):
    """Interface implemented by each dealer's scraper module.

    A scraper's only responsibility is fetching and parsing one dealer's
    listings into `CarListingDTO` objects — no DB access, no business logic
    (see CLAUDE.md's "Layer responsibilities" and "Design Discipline").
    """

    @abstractmethod
    async def scrape(self, tracked: list[TrackedModelSpec] | None = None) -> list[CarListingDTO]:
        """Fetch and parse this dealer's listings into `CarListingDTO`s.

        `tracked` is the set of make/model (optionally variant) combinations
        the user wants scraped, as `TrackedModelSpec`s. Most scrapers (e.g.
        kvd_se, demo) fetch their whole catalog and ignore it; scrapers whose
        site can only be queried per make/model (e.g. bilweb_se) use it to
        build targeted requests. `None`/empty means "nothing tracked" — such
        scrapers should return `[]`.
        """
        raise NotImplementedError
