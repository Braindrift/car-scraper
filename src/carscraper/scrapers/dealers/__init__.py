"""One module (or sub-package) per dealer, each implementing `BaseScraper`.

Importing a dealer module triggers its ``@register`` decorator, adding it to
`scrapers.registry`. List those imports here so "what scrapers exist" stays
greppable in one place (no filesystem scanning — see `registry.py`).
"""

from __future__ import annotations

# bilweb.se: real dealer scraper (CAR-18), registered under "bilweb_se".
from carscraper.scrapers.dealers import bilweb_se as _bilweb_se  # noqa: F401

# bytbil.se: real dealer scraper (CAR-26), registered under "bytbil_se".
from carscraper.scrapers.dealers import bytbil_se as _bytbil_se  # noqa: F401

# Dev/demo-only simulated scrapers (registered under the `demo_*` slugs).
from carscraper.scrapers.dealers import demo as _demo  # noqa: F401

# kvd.se: real dealer scraper (CAR-16), registered under "kvd_se".
from carscraper.scrapers.dealers import kvd_se as _kvd_se  # noqa: F401
