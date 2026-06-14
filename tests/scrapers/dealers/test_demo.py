"""Tests for the dev/demo-only simulated dealer scrapers.

These don't follow the fixture-based pattern (there is no HTML to parse) — the
simulated scrapers generate `CarListingDTO`s in memory. The tests assert the
contract that the `/scrape` and badge demos rely on: every demo slug resolves
to a registered scraper, output is valid `CarListingDTO`s, and the catalog
makes/models line up with the seeded demo `TrackedModel` rows so CAR-12's
filter keeps them.
"""

from __future__ import annotations

import pytest

from carscraper.scrapers.base import CarListingDTO
from carscraper.scrapers.dealers.demo import _SimulatedScraper
from carscraper.scrapers.registry import get_scraper_class, run_scraper

DEMO_SLUGS = ["demo_bilia_stockholm", "demo_hedin_goteborg", "demo_kia_malmo"]

# (make, model, variant) the demo TrackedModel rows match on — see
# services/demo_data._TRACKED_MODELS. variant=None matches any variant.
TRACKED = {
    ("volvo", "v70", None),
    ("volvo", "xc60", "t6 awd"),
    ("kia", "sportage", None),
    ("toyota", "rav4", "hybrid"),
    ("bmw", "320d", None),
}


def _is_tracked(dto: CarListingDTO) -> bool:
    make, model = dto.make.casefold(), dto.model.casefold()
    variant = dto.variant.casefold() if dto.variant else None
    for tm_make, tm_model, tm_variant in TRACKED:
        if tm_make != make or tm_model != model:
            continue
        if tm_variant is None or tm_variant == variant:
            return True
    return False


@pytest.mark.parametrize("slug", DEMO_SLUGS)
def test_demo_slug_resolves_to_simulated_scraper(slug: str) -> None:
    assert issubclass(get_scraper_class(slug), _SimulatedScraper)


@pytest.mark.parametrize("slug", DEMO_SLUGS)
async def test_scrape_returns_valid_tracked_dtos(slug: str) -> None:
    dtos = await run_scraper(slug)

    assert all(isinstance(dto, CarListingDTO) for dto in dtos)
    # Every catalog entry is intended to match a tracked model, so the
    # persistence/diff service keeps them rather than filtering them out.
    assert all(_is_tracked(dto) for dto in dtos)
    assert all(dto.price is not None and dto.price > 0 for dto in dtos)


async def test_repeated_scrapes_can_change_prices() -> None:
    """Across enough runs, at least one listing's price should change.

    The simulated scraper jitters prices so a repeat scrape produces "updated"
    log entries — this guards that the jitter is actually wired up (it would
    fail only if every offset became zero).
    """
    seen: dict[str, set[int]] = {}
    for _ in range(20):
        for dto in await run_scraper("demo_bilia_stockholm"):
            seen.setdefault(dto.external_id, set()).add(dto.price)

    assert any(len(prices) > 1 for prices in seen.values())
