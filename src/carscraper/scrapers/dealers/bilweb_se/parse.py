"""Parsing for bilweb.se search-result cards into `CarListingDTO` (CAR-18).

`parse_listing_cards` translates the raw HTML of one bilweb.se
`/sok/<brand-slug>/<model-slug>` search page into a list of `CarListingDTO`s.
This is the normalization boundary described in CLAUDE.md: every
bilweb.se-specific shape (`div.Card` markup, `dl.Card-carData` rows, fuel
icon classes, "mil" mileage units) is translated here and nowhere else.

Parsing external HTML is a system boundary: a `div.Card` missing its `id`,
detail-page `href`, `data-brand-name`, or `data-model-name` is skipped with a
warning rather than raising (mirrors kvd_se's `parse_auction`).

CAR-23: bilweb.se renders every listing *twice* on a search page - once as a
grid card (`div.Card`, with `dl.Card-carData`) and again as a "row" card
(`div.Card.Card-row`, with a plain `div.Card-carData--row` text blob and no
`dl`) sharing the same `id`. Only the grid variant is selected (see
`parse_listing_cards`); the row variant carries no fuel/transmission data and
its year/mileage are redundant with the grid variant's `dl.Card-carData`.
"""

from __future__ import annotations

import logging
import re

from bs4 import BeautifulSoup, Tag

from carscraper.scrapers.base import CarListingDTO

logger = logging.getLogger(__name__)

# Maps a bilweb.se `Icon--<code>` class (from the `Drivmedel:` row) to the
# `CarListingDTO.fuel_type` string. A combination of electric + gasoline icons
# (plug-in hybrids) maps to "Hybrid"; everything else maps from its single icon.
_FUEL_ICON_MAP = {
    "diesel": "Diesel",
    "gasoline": "Petrol",
    "electric": "Electric",
}

# Trailing 4-digit model year, e.g. "... Skinn 2016" -> strip "2016".
_TRAILING_YEAR_RE = re.compile(r"\s+\d{4}$")

# Non-digit characters in a price string, e.g. "439 700 kr" -> "439700".
_NON_DIGITS_RE = re.compile(r"\D+")

# A 4-digit year embedded in a "Tillv.man" (construction month) value, e.g.
# "2023-11" or "11/2023" -> "2023". Matches the year wherever it falls.
_YEAR_IN_TEXT_RE = re.compile(r"\b(\d{4})\b")

# 1 "mil" (Swedish mile, used for odometer readings) = 10 km.
_MIL_TO_KM = 10


def _text_after_dt(card_data: Tag, label: str) -> str | None:
    """Text of the `<dd>` immediately following the `<dt>` with text `label`.

    `dl.Card-carData` is a flat sequence of `<dt>`/`<dd>` pairs (`Mil:`,
    `Ar:`, optionally `Drivmedel:`); this walks siblings to find the `<dd>`
    paired with a given `<dt>`. Returns `None` if no matching `<dt>` is found.
    """
    for dt in card_data.find_all("dt"):
        if dt.get_text(strip=True).casefold() == label.casefold():
            dd = dt.find_next_sibling("dd")
            return dd.get_text(strip=True) if dd is not None else None
    return None


def _derive_fuel_type(card_data: Tag) -> str | None:
    """Fuel type from the `Drivmedel:` row's `Icon--<code>` span(s).

    Electric + gasoline together (plug-in hybrid) map to "Hybrid". A single
    icon maps via `_FUEL_ICON_MAP`. No `Drivmedel:` row, or an unrecognized
    icon combination, yields `None`.
    """
    for dt in card_data.find_all("dt"):
        if dt.get_text(strip=True).casefold() != "drivmedel:":
            continue
        dd = dt.find_next_sibling("dd")
        if dd is None:
            return None

        codes: set[str] = set()
        for icon in dd.find_all("span", class_="Icon"):
            for cls in icon.get("class", []):
                if cls.startswith("Icon--"):
                    codes.add(cls.removeprefix("Icon--"))

        if codes == {"electric", "gasoline"}:
            return "Hybrid"
        if len(codes) == 1:
            code = next(iter(codes))
            return _FUEL_ICON_MAP.get(code)
        return None

    return None


def _derive_price(card: Tag) -> int | None:
    """`.Card-mainPrice` text (e.g. "439 700 kr") with non-digits stripped."""
    price_el = card.select_one(".Card-mainPrice")
    if price_el is None:
        return None
    digits = _NON_DIGITS_RE.sub("", price_el.get_text())
    return int(digits) if digits else None


def _derive_mileage(card_data: Tag) -> int | None:
    """`Mil:` row's `<dd>`, converted from "mil" to km (x10)."""
    text = _text_after_dt(card_data, "Mil:")
    if text is None:
        return None
    digits = _NON_DIGITS_RE.sub("", text)
    return int(digits) * _MIL_TO_KM if digits else None


def _derive_year(card_data: Tag) -> int | None:
    """`Ar:` row's `<dd>` (bilweb labels this "Ar:" with a Swedish A-ring).

    Matches the ASCII fallback "ar:" too, in case of an encoding mishap. If
    no `Ar:`/`ar:` row is present, falls back to a `Tillv.man:`
    (construction-month) row - a date-ish value like "2023-11" or "11/2023" -
    and extracts the embedded 4-digit year (see `_YEAR_IN_TEXT_RE`). Bilweb's
    search-result cards always carry `Ar:`; the `Tillv.man:` fallback exists
    for markup variants where only construction month is present.
    """
    year_dd: Tag | None = None
    tillv_dd: Tag | None = None

    for dt in card_data.find_all("dt"):
        label = dt.get_text(strip=True).casefold()
        if label in {"år:", "ar:"}:
            year_dd = dt.find_next_sibling("dd")
        elif label in {"tillv.mån:", "tillv.man:"}:
            tillv_dd = dt.find_next_sibling("dd")

    if year_dd is not None:
        text = year_dd.get_text(strip=True)
        if text.isdigit():
            return int(text)
        return None

    if tillv_dd is not None:
        text = tillv_dd.get_text(strip=True)
        match = _YEAR_IN_TEXT_RE.search(text)
        if match:
            return int(match.group(1))
        return None

    return None


def _derive_make_model(card: Tag) -> tuple[str | None, str | None]:
    """`data-brand-name`/`data-model-name` from the first descendant that has them."""
    el = card.find(attrs={"data-brand-name": True, "data-model-name": True})
    if el is None:
        return None, None
    return el.get("data-brand-name"), el.get("data-model-name")


def _derive_variant(alt_text: str | None, make: str, model: str) -> str | None:
    """Variant from the image `alt` text, stripping `make`/`model` prefix and year suffix.

    `Card-heading` is often truncated with "..", but the image `alt` carries
    the full title (e.g. "Volvo XC60 Recharge T6 AWD ... Stol H 2023"). Strips
    a leading "<make> <model>" (case-insensitive) and a trailing 4-digit year,
    mirroring `kvd_se/parse.py::_derive_variant`. Returns `None` if `alt_text`
    is missing or doesn't start with `make`/`model`.
    """
    if not alt_text:
        return None

    prefix = f"{make} {model}"
    if not alt_text.casefold().startswith(prefix.casefold()):
        return None

    remainder = alt_text[len(prefix) :].strip()
    remainder = _TRAILING_YEAR_RE.sub("", remainder).strip()
    return remainder or None


def _derive_image_urls(card: Tag) -> list[str]:
    """`img[data-src]` (lazy-loaded; `src` is a placeholder, not the real image)."""
    img = card.select_one("img[data-src]")
    if img is None:
        return []
    src = img.get("data-src")
    return [src] if src else []


def _parse_card(card: Tag) -> CarListingDTO | None:
    """Translate one `div.Card` into a `CarListingDTO`.

    Returns `None` (and logs) if `id`, the detail-page `href`, or
    `data-brand-name`/`data-model-name` are missing - the fields
    `CarListingDTO` requires.
    """
    external_id = card.get("id")

    link = card.select_one("a.go_to_detail")
    url = link.get("href") if link is not None else None

    make, model = _derive_make_model(card)

    if not external_id or not url or not make or not model:
        logger.warning(
            "Skipping bilweb.se card with missing required field(s): "
            "id=%r href=%r data-brand-name=%r data-model-name=%r",
            external_id,
            url,
            make,
            model,
        )
        return None

    card_data = card.select_one("dl.Card-carData")
    img = card.select_one("img[data-src]")
    alt_text = img.get("alt") if img is not None else None

    return CarListingDTO(
        external_id=str(external_id),
        url=str(url),
        make=str(make),
        model=str(model),
        variant=_derive_variant(alt_text, str(make), str(model)),
        year=_derive_year(card_data) if card_data is not None else None,
        mileage=_derive_mileage(card_data) if card_data is not None else None,
        price=_derive_price(card),
        fuel_type=_derive_fuel_type(card_data) if card_data is not None else None,
        # Not available on search-result cards (neither the grid nor the row
        # variant); only the detail page's "Vaxellada:" field has it. Fetching
        # one detail page per listing is a larger change (N+1 requests) left
        # for a follow-up ticket.
        transmission=None,
        image_urls=_derive_image_urls(card),
    )


def parse_listing_cards(html: str) -> list[CarListingDTO]:
    """Parse every grid `div.Card` on a bilweb.se search page into `CarListingDTO`s.

    bilweb.se renders each listing twice: once as a grid card (`div.Card`,
    with `dl.Card-carData`) and once as a "row" card (`div.Card.Card-row`,
    with a plain `div.Card-carData--row` text blob and no fuel/transmission
    data) sharing the same `id`. `div.Card:not(.Card-row)` selects only the
    grid variant, which is the one that carries `Mil:`/`Ar:`/`Drivmedel:`
    (CAR-23).

    Cards missing a required field are skipped (logged, not raised) - see
    `_parse_card`.
    """
    soup = BeautifulSoup(html, "html.parser")

    listings: list[CarListingDTO] = []
    for card in soup.select("div.Card:not(.Card-row)"):
        dto = _parse_card(card)
        if dto is not None:
            listings.append(dto)

    return listings
