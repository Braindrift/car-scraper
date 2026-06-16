"""Parsing for bytbil.se search-result cards into `CarListingDTO` (CAR-26).

`parse_listing_cards` translates the raw HTML of one bytbil.se search page
(``/bil?Makes=<Make>&Models=<Model>&Regions=...&Page=N``) into a list of
`CarListingDTO`s.  This is the normalization boundary described in CLAUDE.md:
every bytbil.se-specific shape (`li.result-list-item`, `div.uk-grid[data-model-id]`,
`p.uk-text-truncate` year/mileage text, `span.car-price-main`, CSS
`background-image` for the thumbnail) is translated here and nowhere else.

Field notes:
- `external_id`: `data-model-id` attribute on the inner `div.uk-grid.js-link`.
- `url`: ``https://www.bytbil.com`` + `href` from the heading anchor
  (``h3.car-list-header > a``, desktop variant, ``hidden-small-and-below``).
  Falls back to the mobile anchor (``a.js-link-target``) if the desktop one
  is absent.
- `make` / `model`: passed through from the caller; bytbil.se search cards
  don't carry separate make/model attributes.
- `variant`: heading title minus ``"<make> <model> "`` prefix.
- `year`: first ``|``-delimited segment of ``p.uk-text-truncate``.
- `mileage`: second segment — already in Swedish mil (1 mil = 10 km), strip
  ``" mil"`` and ``\\xa0`` thousands separator.  No conversion needed.
- `price`: ``span.car-price-main`` text, strip ``" kr"`` and whitespace.
- `fuel_type`: not available on search-result cards → ``None``.
- `transmission`: not available on search-result cards → ``None``.
- `image_urls`: CSS ``background-image: url(…)`` from ``div.car-image[style]``,
  or ``[]`` when the style attribute is absent / empty (``Bild saknas``).

Cards missing ``data-model-id`` or the detail-page href are skipped with a
warning rather than raising.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from carscraper.scrapers.base import CarListingDTO

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bytbil.com"

# Non-digit characters — used to strip " kr", " mil", \xa0, etc.
_NON_DIGITS_RE = re.compile(r"\D+")

# CSS background-image URL, e.g. "background-image: url(https://...)"
_BG_IMAGE_RE = re.compile(r"background-image:\s*url\(([^)]+)\)")


def _derive_info_segments(card: Tag) -> list[str]:
    """Text segments from ``p.uk-text-truncate`` split on the ``|`` dividers.

    bytbil.se renders this paragraph as::

        2024 <span class="vertical-divider">|</span> 7\xa0093 mil <span ...>|</span> ESLÖV

    ``get_text()`` collapses spans to their text, giving ``"2024 | 7\xa0093 mil | ESLÖV"``.
    Splitting on ``"|"`` yields ``["2024 ", " 7\xa0093 mil ", " ESLÖV"]``.
    """
    p = card.select_one("p.uk-text-truncate")
    if p is None:
        return []
    return p.get_text().split("|")


def _derive_year(segments: list[str]) -> int | None:
    """First segment of the info paragraph, trimmed and parsed as a 4-digit year."""
    if not segments:
        return None
    text = segments[0].strip()
    if text.isdigit() and len(text) == 4:
        return int(text)
    return None


def _derive_mileage(segments: list[str]) -> int | None:
    """Second segment of the info paragraph — already in Swedish mil, strip text.

    E.g. ``" 7\\xa0093 mil "`` → ``7093``.
    """
    if len(segments) < 2:
        return None
    digits = _NON_DIGITS_RE.sub("", segments[1])
    return int(digits) if digits else None


def _derive_price(card: Tag) -> tuple[int | None, str | None]:
    """``span.car-price-main`` text parsed into a numeric price and the raw text.

    Returns ``(price_int, raw_text)`` — ``raw_text`` is the untouched
    ``span.car-price-main`` text (e.g. ``"489\\xa0900 kr"`` or
    ``"2 450 kr/mån"``), used by ``is_leasing_dto`` to detect leasing
    indicators before the text is stripped to digits. Both values are ``None``
    when the element is absent.
    """
    el = card.select_one("span.car-price-main")
    if el is None:
        return None, None
    raw = el.get_text()
    digits = _NON_DIGITS_RE.sub("", raw)
    return (int(digits) if digits else None), raw


def _derive_variant(title: str, make: str, model: str) -> str | None:
    """Heading title minus the ``"<make> <model> "`` prefix.

    E.g. ``"Volvo XC60 T6 Core Special Edition"`` with make ``"Volvo"`` and
    model ``"XC60"`` → ``"T6 Core Special Edition"``.  Returns ``None`` if the
    title doesn't start with ``"<make> <model>"``.
    """
    prefix = f"{make} {model}"
    if not title.casefold().startswith(prefix.casefold()):
        return None
    remainder = title[len(prefix) :].strip()
    return remainder or None


def _derive_url(card: Tag) -> str | None:
    """Detail-page href from the desktop heading anchor, with bytbil base prepended.

    The desktop anchor (``h3.car-list-header.hidden-small-and-below > a``) is
    preferred because it's the canonical heading link. Falls back to the mobile
    anchor (``a.js-link-target``) which carries the same href.
    """
    # Desktop variant: inside h3.hidden-small-and-below
    h3 = card.select_one("h3.car-list-header.hidden-small-and-below")
    if h3 is not None:
        a = h3.select_one("a[href]")
        if a is not None:
            return BASE_URL + a["href"]

    # Mobile fallback
    a = card.select_one("a.js-link-target[href]")
    if a is not None:
        return BASE_URL + a["href"]

    return None


def _derive_title(card: Tag) -> str | None:
    """Heading text (full listing title) from the desktop anchor."""
    h3 = card.select_one("h3.car-list-header.hidden-small-and-below")
    if h3 is not None:
        a = h3.select_one("a")
        if a is not None:
            return a.get_text(strip=True)

    a = card.select_one("a.js-link-target")
    if a is not None:
        return a.get_text(strip=True)

    return None


def _derive_image_urls(card: Tag) -> list[str]:
    """CSS ``background-image: url(…)`` from ``div.car-image``, or ``[]``.

    bytbil.se uses a CSS background image instead of an ``<img>`` tag for
    listing thumbnails.  When no image is available the style attribute is
    absent or empty (``""``) — in that case we return ``[]``.
    """
    div = card.select_one("div.car-image")
    if div is None:
        return []
    style = div.get("style", "")
    m = _BG_IMAGE_RE.search(style)
    if not m:
        return []
    url = m.group(1).strip()
    return [url] if url else []


def _parse_card(card: Tag, make: str, model: str) -> CarListingDTO | None:
    """Translate one ``li.result-list-item`` inner grid into a ``CarListingDTO``.

    Returns ``None`` (and logs a warning) if ``data-model-id`` or the
    detail-page href are missing — the two fields ``CarListingDTO`` requires
    that bytbil.se must supply.
    """
    grid = card.select_one("div.uk-grid.js-link[data-model-id]")
    if grid is None:
        logger.warning("Skipping bytbil.se card: no div[data-model-id] found")
        return None

    external_id = grid.get("data-model-id")
    url = _derive_url(card)

    if not external_id or not url:
        logger.warning(
            "Skipping bytbil.se card with missing required field(s): " "data-model-id=%r url=%r",
            external_id,
            url,
        )
        return None

    title = _derive_title(card) or ""
    segments = _derive_info_segments(card)
    price, raw_price_text = _derive_price(card)

    return CarListingDTO(
        external_id=str(external_id),
        url=url,
        make=make,
        model=model,
        variant=_derive_variant(title, make, model),
        year=_derive_year(segments),
        mileage=_derive_mileage(segments),
        price=price,
        raw_price_text=raw_price_text,
        fuel_type=None,
        transmission=None,
        image_urls=_derive_image_urls(card),
    )


def parse_listing_cards(html: str, make: str, model: str) -> list[CarListingDTO]:
    """Parse every ``li.result-list-item`` on a bytbil.se search page.

    `make` and `model` are passed through from the ``TrackedModelSpec`` that
    triggered this request — bytbil.se search cards don't carry separate
    make/model attributes, so the caller supplies them.

    Cards missing ``data-model-id`` or the detail-page href are skipped (logged,
    not raised) — see ``_parse_card``.
    """
    soup = BeautifulSoup(html, "html.parser")

    listings: list[CarListingDTO] = []
    for li in soup.select("li.result-list-item"):
        dto = _parse_card(li, make, model)
        if dto is not None:
            listings.append(dto)

    return listings
