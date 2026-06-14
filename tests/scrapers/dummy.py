"""Test-only dummy scraper used to exercise `BaseScraper` and the registry.

Registered under the slug `"dummy"`. Returns static `CarListingDTO`s without
any network/Playwright/httpx usage, per CAR-3's "out of scope" note.
"""

from __future__ import annotations

from carscraper.scrapers.base import BaseScraper, CarListingDTO
from carscraper.scrapers.registry import register

DUMMY_LISTINGS: list[CarListingDTO] = [
    CarListingDTO(
        external_id="dummy-1",
        url="https://example.com/listings/dummy-1",
        make="Volvo",
        model="V70",
        variant="T5",
        year=2018,
        mileage=85000,
        price=189000,
        fuel_type="Petrol",
        transmission="Automatic",
    ),
    CarListingDTO(
        external_id="dummy-2",
        url="https://example.com/listings/dummy-2",
        make="Toyota",
        model="Corolla",
    ),
]


@register("dummy")
class DummyScraper(BaseScraper):
    """Returns a static list of `CarListingDTO`s."""

    async def scrape(self) -> list[CarListingDTO]:
        return list(DUMMY_LISTINGS)
