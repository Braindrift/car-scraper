"""kvd.se dealer scraper package (CAR-16).

Importing `scraper` triggers `@register("kvd_se")`, registering
`KvdSeScraper`. See `dealers/__init__.py` for the import that wires this
package into the scraper registry.
"""

from __future__ import annotations

from carscraper.scrapers.dealers.kvd_se import scraper as _scraper  # noqa: F401
