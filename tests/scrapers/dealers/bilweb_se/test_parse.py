"""Tests for `parse_listing_cards`'s field mapping (CAR-18, CAR-23).

Exercises the field-mapping table from CAR-18 against trimmed real captures
of `https://bilweb.se/sok/peugeot/5008` (`fixtures/peugeot_5008.html`) and
`https://bilweb.se/sok/volvo/xc60` (`fixtures/volvo_xc60.html`).

CAR-23 adds `fixtures/volvo_xc60_rows.html`, covering the "row card"
duplication bug (every search-result listing also appears as a
`div.Card.Card-row` with no `dl.Card-carData`, sharing the same `id` as its
grid-card counterpart) plus the `Tillv.mån:` year fallback.
"""

from __future__ import annotations

from pathlib import Path

from carscraper.scrapers.base import CarListingDTO
from carscraper.scrapers.dealers.bilweb_se.parse import parse_listing_cards

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _by_id(dtos: list[CarListingDTO]) -> dict[str, CarListingDTO]:
    return {dto.external_id: dto for dto in dtos}


# --- peugeot_5008.html -------------------------------------------------------


def test_diesel_card_field_mapping() -> None:
    """Card 12744081: diesel, full (non-truncated) heading, mileage in mil."""
    dtos = _by_id(parse_listing_cards(_load("peugeot_5008.html")))
    dto = dtos["12744081"]

    assert dto.url == (
        "https://bilweb.se/stockholms-lan/"
        "peugeot-5008-1-6-bluehdi-120-euro-6-7-sits-aut-2016-suv-12744081"
    )
    assert dto.make == "Peugeot"
    assert dto.model == "5008"
    assert dto.variant == "1.6 BlueHDi 120 Euro 6 7-sits Aut"
    assert dto.year == 2016
    assert dto.mileage == 14295  # 14 295 mil
    assert dto.price == 89900
    assert dto.fuel_type == "Diesel"
    assert dto.transmission is None
    assert dto.image_urls == ["https://bilweb.se/i?u=107366205&w=400&h=250&c=1"]


def test_gasoline_card_field_mapping() -> None:
    """Card 12740039: gasoline icon -> fuel_type "Petrol"."""
    dtos = _by_id(parse_listing_cards(_load("peugeot_5008.html")))
    dto = dtos["12740039"]

    assert dto.make == "Peugeot"
    assert dto.model == "5008"
    assert dto.variant == "GT PureTech 130 AUT"
    assert dto.year == 2023
    assert dto.mileage == 3087  # 3 087 mil
    assert dto.price == 279800
    assert dto.fuel_type == "Petrol"


def test_electric_gasoline_combo_maps_to_hybrid() -> None:
    """Card 12743030: electric+gasoline icon combo -> fuel_type "Hybrid"."""
    dtos = _by_id(parse_listing_cards(_load("peugeot_5008.html")))
    dto = dtos["12743030"]

    assert dto.make == "Peugeot"
    assert dto.model == "5008"
    assert dto.fuel_type == "Hybrid"
    assert dto.price == 3599
    assert dto.mileage == 1  # 1 mil
    assert dto.year == 2026


# --- volvo_xc60.html ----------------------------------------------------------


def test_no_drivmedel_row_yields_none_fuel_type() -> None:
    """Card 12744401: no `Drivmedel:` row at all -> fuel_type is None."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html")))
    dto = dtos["12744401"]

    assert dto.make == "Volvo"
    assert dto.model == "XC60"
    assert dto.fuel_type is None


def test_variant_derived_from_truncated_heading_via_alt_text() -> None:
    """Card 12744401: `Card-heading` is truncated with ".." but the image
    `alt` carries the full title - variant strips the "Volvo XC60 " prefix
    and the trailing " 2023" year."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html")))
    dto = dtos["12744401"]

    assert dto.variant == "Recharge T6 AWD Geartronic Core Edition Drag El Stol H"
    assert dto.year == 2023
    assert dto.price == 439700
    assert dto.mileage == 5641  # 5 641 mil


def test_diesel_card_with_truncated_heading_mileage_conversion() -> None:
    """Card 12744358: diesel, truncated heading, mileage 20 600 mil."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html")))
    dto = dtos["12744358"]

    assert dto.make == "Volvo"
    assert dto.model == "XC60"
    assert dto.variant == "D4 AWD Summum VOC Varmare Dragkrok Skinn"
    assert dto.year == 2016
    assert dto.mileage == 20600  # 20 600 mil
    assert dto.fuel_type == "Diesel"


# --- volvo_xc60_rows.html (CAR-23: row-card duplication) -----------------------


def test_row_card_duplicates_do_not_produce_extra_or_blank_listings() -> None:
    """Each listing appears as both a grid `div.Card` and a `div.Card.Card-row`
    sharing the same `id`; only the grid variant is parsed."""
    dtos = parse_listing_cards(_load("volvo_xc60_rows.html"))

    assert len(dtos) == 3
    assert {dto.external_id for dto in dtos} == {"12745960", "12745948", "12745866"}


def test_row_card_duplicate_does_not_null_out_grid_fields() -> None:
    """Card 12745960: hybrid, mileage 10 991 mil, year 2024 - the grid card's
    data, not the row card's `None`s."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60_rows.html")))
    dto = dtos["12745960"]

    assert dto.year == 2024
    assert dto.mileage == 10991  # 10 991 mil
    assert dto.fuel_type == "Hybrid"


def test_row_card_diesel_listing_keeps_grid_fields() -> None:
    """Card 12745948: diesel, mileage 15 490 mil, year 2015."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60_rows.html")))
    dto = dtos["12745948"]

    assert dto.year == 2015
    assert dto.mileage == 15490  # 15 490 mil
    assert dto.fuel_type == "Diesel"


def test_row_card_listing_without_drivmedel_row_yields_none_fuel_type() -> None:
    """Card 12745866: no `Drivmedel:` row on the grid card -> fuel_type None,
    but year/mileage are still populated from the grid card's `dl`."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60_rows.html")))
    dto = dtos["12745866"]

    assert dto.year == 2025
    assert dto.mileage == 5625  # 5 625 mil
    assert dto.fuel_type is None


# --- _derive_year Tillv.mån fallback (CAR-23) -----------------------------------


def test_year_falls_back_to_tillv_man_when_ar_row_is_missing() -> None:
    """No `Ar:` row, but a `Tillv.mån:` row with "2023-11" -> year 2023."""
    html = """
    <div class="Card" id="1">
      <img data-src="https://bilweb.se/i?u=1" alt="Volvo XC60 T6 2023">
      <h3 class="Card-heading">
        <a class="go_to_detail" href="https://bilweb.se/x-1">Volvo XC60 T6</a>
      </h3>
      <a data-track-event="monthly_cost_list" data-dealer-name="D"
         data-brand-name="Volvo" data-model-name="XC60">link</a>
      <dl class="Card-carData">
        <dt>Mil:</dt><dd>1 000</dd>
        <dt>Tillv.mån:</dt><dd>2023-11</dd>
      </dl>
    </div>
    """
    dtos = parse_listing_cards(html)

    assert len(dtos) == 1
    assert dtos[0].year == 2023
    assert dtos[0].mileage == 1000  # 1 000 mil


def test_year_falls_back_to_tillv_man_with_month_slash_year_format() -> None:
    """`Tillv.mån:` formatted as "03/2023" (month/year) -> year 2023."""
    html = """
    <div class="Card" id="1">
      <img data-src="https://bilweb.se/i?u=1" alt="Volvo XC60 T6 2023">
      <h3 class="Card-heading">
        <a class="go_to_detail" href="https://bilweb.se/x-1">Volvo XC60 T6</a>
      </h3>
      <a data-track-event="monthly_cost_list" data-dealer-name="D"
         data-brand-name="Volvo" data-model-name="XC60">link</a>
      <dl class="Card-carData">
        <dt>Mil:</dt><dd>1 000</dd>
        <dt>Tillv.mån:</dt><dd>03/2023</dd>
      </dl>
    </div>
    """
    dtos = parse_listing_cards(html)

    assert dtos[0].year == 2023


def test_ar_row_takes_precedence_over_tillv_man() -> None:
    """Both `Ar:` and `Tillv.mån:` present -> `Ar:` wins."""
    html = """
    <div class="Card" id="1">
      <img data-src="https://bilweb.se/i?u=1" alt="Volvo XC60 T6 2020">
      <h3 class="Card-heading">
        <a class="go_to_detail" href="https://bilweb.se/x-1">Volvo XC60 T6</a>
      </h3>
      <a data-track-event="monthly_cost_list" data-dealer-name="D"
         data-brand-name="Volvo" data-model-name="XC60">link</a>
      <dl class="Card-carData">
        <dt>Mil:</dt><dd>1 000</dd>
        <dt>Ar:</dt><dd>2020</dd>
        <dt>Tillv.mån:</dt><dd>2019-12</dd>
      </dl>
    </div>
    """
    dtos = parse_listing_cards(html)

    assert dtos[0].year == 2020


def test_no_year_or_tillv_man_row_yields_none_year() -> None:
    html = """
    <div class="Card" id="1">
      <img data-src="https://bilweb.se/i?u=1" alt="Volvo XC60 T6">
      <h3 class="Card-heading">
        <a class="go_to_detail" href="https://bilweb.se/x-1">Volvo XC60 T6</a>
      </h3>
      <a data-track-event="monthly_cost_list" data-dealer-name="D"
         data-brand-name="Volvo" data-model-name="XC60">link</a>
      <dl class="Card-carData">
        <dt>Mil:</dt><dd>1 000</dd>
      </dl>
    </div>
    """
    dtos = parse_listing_cards(html)

    assert dtos[0].year is None


# --- skip paths ----------------------------------------------------------------


def test_card_missing_id_is_skipped() -> None:
    html = """
    <div class="Card ">
      <img data-src="https://bilweb.se/i?u=1" alt="Volvo XC60 T6 2020">
      <h3 class="Card-heading">
        <a class="go_to_detail" href="https://bilweb.se/x-1">Volvo XC60 T6</a>
      </h3>
      <a data-track-event="monthly_cost_list" data-dealer-name="D"
         data-brand-name="Volvo" data-model-name="XC60">link</a>
      <dl class="Card-carData"><dt>Mil:</dt><dd>1 000</dd><dt>Ar:</dt><dd>2020</dd></dl>
    </div>
    """
    assert parse_listing_cards(html) == []


def test_card_missing_href_is_skipped() -> None:
    html = """
    <div class="Card " id="1">
      <img data-src="https://bilweb.se/i?u=1" alt="Volvo XC60 T6 2020">
      <h3 class="Card-heading"><a class="go_to_detail">Volvo XC60 T6</a></h3>
      <a data-track-event="monthly_cost_list" data-dealer-name="D"
         data-brand-name="Volvo" data-model-name="XC60">link</a>
      <dl class="Card-carData"><dt>Mil:</dt><dd>1 000</dd><dt>Ar:</dt><dd>2020</dd></dl>
    </div>
    """
    assert parse_listing_cards(html) == []


def test_card_missing_brand_and_model_attrs_is_skipped() -> None:
    html = """
    <div class="Card " id="1">
      <img data-src="https://bilweb.se/i?u=1" alt="Volvo XC60 T6 2020">
      <h3 class="Card-heading">
        <a class="go_to_detail" href="https://bilweb.se/x-1">Volvo XC60 T6</a>
      </h3>
      <dl class="Card-carData"><dt>Mil:</dt><dd>1 000</dd><dt>Ar:</dt><dd>2020</dd></dl>
    </div>
    """
    assert parse_listing_cards(html) == []


def test_valid_card_alongside_invalid_card_keeps_only_valid() -> None:
    valid = _load("peugeot_5008.html")
    invalid = """
    <div class="Card " id="999999">
      <img data-src="https://bilweb.se/i?u=1" alt="Volvo XC60 T6 2020">
      <h3 class="Card-heading"><a class="go_to_detail">Volvo XC60 T6</a></h3>
      <dl class="Card-carData"><dt>Mil:</dt><dd>1 000</dd><dt>Ar:</dt><dd>2020</dd></dl>
    </div>
    """
    dtos = parse_listing_cards(valid + invalid)
    assert "999999" not in {dto.external_id for dto in dtos}
    assert len(dtos) == 3
