"""bytbil.se dealer scraper package (CAR-26).

Importing `scraper` triggers `@register("bytbil_se")`, registering
`BytbilSeScraper`. See `dealers/__init__.py` for the import that wires this
package into the scraper registry.
"""

from __future__ import annotations

from carscraper.scrapers.dealers.bytbil_se import scraper as _scraper  # noqa: F401
