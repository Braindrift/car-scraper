"""Simulated dealer scrapers (dev/demo-only).

**Dev/demo-only.** These let the `/scrape` page (CAR-13) and the dashboard
NEW/UPDATED badges (CAR-14) be exercised end to end without a real dealer
site. They implement the same `BaseScraper` contract a real dealer will, but
instead of fetching/parsing HTML they emit `CarListingDTO`s from a fixed
in-memory catalog with small random variations on each run:

- a listing's price jitters between runs -> recorded as **updated**;
- a listing is occasionally dropped from a run -> **removed**, and reappears
  on a later run -> **new** again.

So clicking "Scrape" a couple of times produces a visible change report and a
mix of badges, which is exactly what CAR-13/14 need to be verified.

These are registered under the `demo_*` slugs that
`services/demo_data.py` seeds, so after `seed-demo-data` the demo dealers are
immediately scrapeable. The catalog makes/models line up with the demo
`TrackedModel` rows (Volvo V70, Volvo XC60 "T6 AWD", Toyota RAV4 "Hybrid",
BMW 320d, Kia Sportage) so the persistence/diff service (CAR-12) keeps them.

External ids use a ``sim-`` prefix, distinct from the ``demo-`` listings that
`seed-demo-data` creates directly, so the simulated scrapes and the seeded
image listings (CAR-15) coexist without colliding.

Real dealer scrapers (step 3) are added as separate modules in this package;
this one is purely for verification and must never stand in for a real dealer.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from carscraper.scrapers.base import BaseScraper, CarListingDTO, TrackedModelSpec
from carscraper.scrapers.registry import register


@dataclass(frozen=True)
class _CatalogEntry:
    """A simulated listing's stable fields; price is generated per run."""

    external_id: str
    make: str
    model: str
    variant: str | None
    year: int
    mileage: int
    base_price: int
    fuel_type: str
    transmission: str


# Price jitter applied to a catalog entry's `base_price` each run, in SEK.
# Mostly non-zero so a repeat scrape is very likely to register a price change
# (an "updated" entry) on at least some listings.
_PRICE_OFFSETS = [-15_000, -10_000, -5_000, 0, 5_000, 10_000]

# Probability a given catalog entry is *included* in a run. <1 so listings
# occasionally drop out (-> "removed") and come back later (-> "new").
_INCLUDE_PROBABILITY = 0.85


class _SimulatedScraper(BaseScraper):
    """Base for the per-dealer simulated scrapers.

    Subclasses set `slug` (matching `Dealer.scraper_module`) and `catalog`.
    `scrape()` returns each catalog entry with ~85% probability and a randomly
    jittered price, so successive runs differ.
    """

    slug: str
    catalog: list[_CatalogEntry]

    async def scrape(self, tracked: list[TrackedModelSpec] | None = None) -> list[CarListingDTO]:
        # Simulated catalog is fixed and already lines up with the demo
        # TrackedModel rows (see module docstring) - `tracked` is ignored.
        dtos: list[CarListingDTO] = []
        for entry in self.catalog:
            if random.random() > _INCLUDE_PROBABILITY:
                continue
            price = entry.base_price + random.choice(_PRICE_OFFSETS)
            dtos.append(
                CarListingDTO(
                    external_id=entry.external_id,
                    url=f"https://example.test/{self.slug}/{entry.external_id}",
                    make=entry.make,
                    model=entry.model,
                    variant=entry.variant,
                    year=entry.year,
                    mileage=entry.mileage,
                    price=price,
                    fuel_type=entry.fuel_type,
                    transmission=entry.transmission,
                )
            )
        return dtos


@register("demo_bilia_stockholm")
class BiliaStockholmDemoScraper(_SimulatedScraper):
    """Simulated Volvo-heavy dealer (matches the V70 / XC60 tracked models)."""

    slug = "demo_bilia_stockholm"
    catalog = [
        _CatalogEntry(
            external_id="sim-bilia-1",
            make="Volvo",
            model="V70",
            variant="D4 Momentum",
            year=2018,
            mileage=96_000,
            base_price=179_900,
            fuel_type="Diesel",
            transmission="Automatic",
        ),
        _CatalogEntry(
            external_id="sim-bilia-2",
            make="Volvo",
            model="XC60",
            # Must equal the tracked variant exactly to match (see CAR-12's
            # _matches_tracked): TrackedModel("Volvo", "XC60", "T6 AWD").
            variant="T6 AWD",
            year=2020,
            mileage=52_000,
            base_price=369_900,
            fuel_type="Petrol",
            transmission="Automatic",
        ),
        _CatalogEntry(
            external_id="sim-bilia-3",
            make="Volvo",
            model="V70",
            variant="T5 Summum",
            year=2017,
            mileage=121_000,
            base_price=159_900,
            fuel_type="Petrol",
            transmission="Automatic",
        ),
    ]


@register("demo_hedin_goteborg")
class HedinGoteborgDemoScraper(_SimulatedScraper):
    """Simulated Toyota/BMW dealer (matches the RAV4 Hybrid / 320d models)."""

    slug = "demo_hedin_goteborg"
    catalog = [
        _CatalogEntry(
            external_id="sim-hedin-1",
            make="Toyota",
            model="RAV4",
            # Matches TrackedModel("Toyota", "RAV4", "Hybrid").
            variant="Hybrid",
            year=2021,
            mileage=41_000,
            base_price=334_900,
            fuel_type="Hybrid",
            transmission="Automatic",
        ),
        _CatalogEntry(
            external_id="sim-hedin-2",
            make="BMW",
            model="320d",
            variant="Touring xDrive",
            year=2019,
            mileage=88_000,
            base_price=244_900,
            fuel_type="Diesel",
            transmission="Automatic",
        ),
        _CatalogEntry(
            external_id="sim-hedin-3",
            make="BMW",
            model="320d",
            variant="Sedan Sport Line",
            year=2020,
            mileage=60_000,
            base_price=269_900,
            fuel_type="Diesel",
            transmission="Automatic",
        ),
    ]


@register("demo_kia_malmo")
class KiaMalmoDemoScraper(_SimulatedScraper):
    """Simulated Kia dealer (matches the Sportage tracked model)."""

    slug = "demo_kia_malmo"
    catalog = [
        _CatalogEntry(
            external_id="sim-kia-1",
            make="Kia",
            model="Sportage",
            variant="1.6 T-GDI GT-Line",
            year=2021,
            mileage=34_000,
            base_price=299_900,
            fuel_type="Petrol",
            transmission="Automatic",
        ),
        _CatalogEntry(
            external_id="sim-kia-2",
            make="Kia",
            model="Sportage",
            variant="1.6 CRDi Action",
            year=2019,
            mileage=70_000,
            base_price=219_900,
            fuel_type="Diesel",
            transmission="Manual",
        ),
    ]
