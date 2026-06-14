"""bilweb.se dealer scraper package (CAR-18).

Importing `scraper` triggers `@register("bilweb_se")`, registering
`BilwebSeScraper`. See `dealers/__init__.py` for the import that wires this
package into the scraper registry.
"""

from __future__ import annotations

from carscraper.scrapers.dealers.bilweb_se import scraper as _scraper  # noqa: F401
