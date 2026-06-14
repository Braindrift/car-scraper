"""Scraper registry: resolves a `Dealer.scraper_module` slug to a `BaseScraper`.

Dealer scrapers register themselves with `@register("<slug>")`, where
`<slug>` matches `Dealer.scraper_module` (see CLAUDE.md's "Dealer scraper
naming" convention, e.g. `bilia_stockholm`). This is a simple, explicit
mechanism: importing a dealer module triggers its `@register` decorator,
which adds it to the registry. No filesystem scanning is needed — the set of
enabled dealer modules is small (5-10) and explicit imports keep "what
scrapers exist" easy to grep for.

This module deliberately knows nothing about the DB — it maps slugs to
`BaseScraper` subclasses and can instantiate/run them. Wiring this up to real
`Dealer` rows (looking up `scraper_module` for enabled dealers and running
each) is a `services/` concern for a later ticket.
"""

from __future__ import annotations

from carscraper.scrapers.base import BaseScraper, CarListingDTO

_REGISTRY: dict[str, type[BaseScraper]] = {}


def register(slug: str):
    """Class decorator registering a `BaseScraper` subclass under `slug`.

    `slug` should match the dealer's `Dealer.scraper_module` value.
    """

    def decorator(cls: type[BaseScraper]) -> type[BaseScraper]:
        if slug in _REGISTRY and _REGISTRY[slug] is not cls:
            raise ValueError(
                f"Scraper slug {slug!r} is already registered to "
                f"{_REGISTRY[slug].__name__}, cannot register {cls.__name__}"
            )
        _REGISTRY[slug] = cls
        return cls

    return decorator


def get_scraper_class(slug: str) -> type[BaseScraper]:
    """Look up the `BaseScraper` subclass registered under `slug`.

    Raises `KeyError` if no scraper is registered for `slug`.
    """

    try:
        return _REGISTRY[slug]
    except KeyError:
        raise KeyError(f"No scraper registered for slug {slug!r}") from None


async def run_scraper(slug: str) -> list[CarListingDTO]:
    """Instantiate and run the scraper registered under `slug`.

    Returns the `CarListingDTO`s produced by that scraper's `scrape()`.
    """

    scraper_cls = get_scraper_class(slug)
    scraper = scraper_cls()
    return await scraper.scrape()


# Importing the dealers package triggers each dealer module's `@register`
# decorator, populating `_REGISTRY`. Done at the bottom so `register` is
# already defined when the dealer modules import it (avoids a circular import).
from carscraper.scrapers import dealers as _dealers  # noqa: E402,F401
