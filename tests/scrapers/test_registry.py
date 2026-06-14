"""Registry tests: resolving and running a scraper by slug.

Uses `tests/scrapers/dummy.py`'s `DummyScraper`, registered under the slug
`"dummy"`, as a stand-in for a real dealer scraper (no `Dealer` rows or
network access needed for this ticket).
"""

from __future__ import annotations

import pytest

from carscraper.scrapers.base import CarListingDTO
from carscraper.scrapers.registry import get_scraper_class, register, run_scraper
from tests.scrapers.dummy import DUMMY_LISTINGS, DummyScraper


def test_get_scraper_class_resolves_registered_slug() -> None:
    assert get_scraper_class("dummy") is DummyScraper


def test_get_scraper_class_unknown_slug_raises_key_error() -> None:
    with pytest.raises(KeyError):
        get_scraper_class("does-not-exist")


async def test_run_scraper_returns_dtos_from_dummy_scraper() -> None:
    listings = await run_scraper("dummy")

    assert listings == DUMMY_LISTINGS
    assert all(isinstance(listing, CarListingDTO) for listing in listings)


def test_register_same_slug_twice_with_same_class_is_ok() -> None:
    # Re-registering the exact same class under its existing slug (e.g. if
    # the module is imported more than once) must not raise.
    register("dummy")(DummyScraper)
    assert get_scraper_class("dummy") is DummyScraper


def test_register_same_slug_twice_with_different_class_raises() -> None:
    class OtherScraper(DummyScraper):
        pass

    with pytest.raises(ValueError, match="already registered"):
        register("dummy")(OtherScraper)
