"""Tests for `parse_listing_cards` field mapping (CAR-26).

Exercises the field-mapping table from CAR-26 against a trimmed real capture
of ``https://www.bytbil.com/bil?Makes=Volvo&Models=XC60&Regions=Sk%C3%A5ne+l%C3%A4n&Page=2``
(``fixtures/volvo_xc60.html``, 3 cards).

Card inventory:
- 19217540: 2025, 4 466 mil, 489 900 kr, NO image (``Bild saknas``)
- 19217474: 2024, 7 093 mil, 499 900 kr, HAS image (bbcdn.io)
- 19215626: 2015, 14 391 mil, 184 900 kr, HAS image (bbcdn.io)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from carscraper.scrapers.base import CarListingDTO
from carscraper.scrapers.dealers.bytbil_se.parse import parse_listing_cards

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _by_id(dtos: list[CarListingDTO]) -> dict[str, CarListingDTO]:
    return {dto.external_id: dto for dto in dtos}


# --- fixture card count -------------------------------------------------------


def test_parse_returns_three_cards() -> None:
    dtos = parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60")
    assert len(dtos) == 3


# --- card 19217540: 2025, 4 466 mil, 489 900 kr, no image --------------------


def test_card_19217540_required_fields() -> None:
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19217540"]

    assert dto.external_id == "19217540"
    assert dto.url == (
        "https://www.bytbil.com" "/skane-lan/personbil-xc60-t6-core-special-edition-1240-19217540"
    )
    assert dto.make == "Volvo"
    assert dto.model == "XC60"


def test_card_19217540_year_mileage_price() -> None:
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19217540"]

    assert dto.year == 2025
    assert dto.mileage == 4466  # 4 466 mil
    assert dto.price == 489900


def test_card_19217540_variant() -> None:
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19217540"]

    assert dto.variant == "T6 Core Special Edition"


def test_card_19217540_no_image() -> None:
    """Card with empty style attribute (``Bild saknas``) → image_urls == []."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19217540"]

    assert dto.image_urls == []


def test_card_19217540_fuel_and_transmission_are_none() -> None:
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19217540"]

    assert dto.fuel_type is None
    assert dto.transmission is None


# --- card 19217474: 2024, 7 093 mil, 499 900 kr, has image -------------------


def test_card_19217474_year_mileage_price() -> None:
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19217474"]

    assert dto.year == 2024
    assert dto.mileage == 7093  # 7 093 mil (\xa0 thousands separator)
    assert dto.price == 499900


def test_card_19217474_image_url() -> None:
    """Card with background-image style → image_urls has one URL."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19217474"]

    assert dto.image_urls == [
        "https://pro.bbcdn.io/4a/4ac84a45-c3f3-f40a-9b0b-00005cf70fbf?rule=legacy-main"
    ]


def test_card_19217474_variant() -> None:
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19217474"]

    assert dto.variant == "Recharge T6 Plus Dark"


# --- card 19215626: 2015, 14 391 mil, 184 900 kr, has image ------------------


def test_card_19215626_year_mileage_price() -> None:
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19215626"]

    assert dto.year == 2015
    assert dto.mileage == 14391  # 14 391 mil
    assert dto.price == 184900


def test_card_19215626_image_url() -> None:
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60"))
    dto = dtos["19215626"]

    assert dto.image_urls == [
        "https://pro.bbcdn.io/96/96397428-1360-f8e2-1030-0000802d6fc9?rule=legacy-main"
    ]


# --- make/model pass-through -------------------------------------------------


def test_make_model_passed_through_from_caller() -> None:
    """make/model come from the caller, not from card HTML."""
    dtos = parse_listing_cards(_load("volvo_xc60.html"), "Volvo", "XC60")
    assert all(dto.make == "Volvo" for dto in dtos)
    assert all(dto.model == "XC60" for dto in dtos)


# --- skip paths ---------------------------------------------------------------


def test_card_missing_data_model_id_is_skipped() -> None:
    html = """
    <ul class="result-list">
      <li class="result-list-item">
        <div class="uk-grid js-link">
          <div class="description">
            <h3 class="car-list-header hidden-small-and-below">
              <a href="/some/path">Volvo XC60 T6</a>
            </h3>
            <p class="uk-text-truncate">2024 | 5 000 mil | MALMÖ</p>
          </div>
          <span class="car-price-main">300 000 kr</span>
          <div class="car-image" style="background-image: url(https://example.com/img.jpg)"></div>
        </div>
      </li>
    </ul>
    """
    assert parse_listing_cards(html, "Volvo", "XC60") == []


def test_card_missing_href_is_skipped() -> None:
    html = """
    <ul class="result-list">
      <li class="result-list-item">
        <div class="uk-grid js-link uk-flex-row-reverse" data-model-id="99999">
          <div class="description">
            <h3 class="car-list-header hidden-small-and-below">
              <a>Volvo XC60 T6 (no href)</a>
            </h3>
            <p class="uk-text-truncate">2024 | 5 000 mil | MALMÖ</p>
          </div>
          <span class="car-price-main">300 000 kr</span>
          <div class="car-image" style=""></div>
        </div>
      </li>
    </ul>
    """
    assert parse_listing_cards(html, "Volvo", "XC60") == []


def test_empty_page_returns_empty_list() -> None:
    html = "<html><body><ul class='result-list'></ul></body></html>"
    assert parse_listing_cards(html, "Volvo", "XC60") == []


def test_valid_card_alongside_invalid_keeps_only_valid() -> None:
    valid_html = _load("volvo_xc60.html")
    # Inject an invalid card (missing data-model-id) before the list closes
    invalid = """
    <li class="result-list-item">
      <div class="uk-grid js-link uk-flex-row-reverse">
        <div class="description">
          <h3 class="car-list-header hidden-small-and-below">
            <a href="/bad-card">Bad Card</a>
          </h3>
          <p class="uk-text-truncate">2023 | 1 000 mil | LUND</p>
        </div>
        <span class="car-price-main">100 000 kr</span>
        <div class="car-image" style=""></div>
      </div>
    </li>
    """
    combined = valid_html.replace("</ul>", invalid + "</ul>")
    dtos = parse_listing_cards(combined, "Volvo", "XC60")
    assert len(dtos) == 3
    assert all(dto.external_id in {"19217540", "19217474", "19215626"} for dto in dtos)


# --- mileage edge cases -------------------------------------------------------


@pytest.mark.parametrize(
    "mileage_text,expected",
    [
        ("0 mil", 0),
        ("4\xa0466 mil", 4466),
        ("14\xa0391 mil", 14391),
    ],
)
def test_mileage_parsing(mileage_text: str, expected: int) -> None:
    html = f"""
    <ul class="result-list">
      <li class="result-list-item">
        <div class="uk-grid js-link uk-flex-row-reverse" data-model-id="12345">
          <div class="description">
            <h3 class="car-list-header hidden-small-and-below">
              <a href="/test/path">Volvo XC60 T6</a>
            </h3>
            <p class="uk-text-truncate">2024 | {mileage_text} | MALMÖ</p>
          </div>
          <span class="car-price-main">300\xa0000 kr</span>
          <div class="car-image" style=""></div>
        </div>
      </li>
    </ul>
    """
    dtos = parse_listing_cards(html, "Volvo", "XC60")
    assert len(dtos) == 1
    assert dtos[0].mileage == expected
