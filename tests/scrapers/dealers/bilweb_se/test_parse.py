"""Tests for `parse_listing_cards`'s field mapping (CAR-18).

Exercises the field-mapping table from CAR-18 against trimmed real captures
of `https://bilweb.se/sok/peugeot/5008` (`fixtures/peugeot_5008.html`) and
`https://bilweb.se/sok/volvo/xc60` (`fixtures/volvo_xc60.html`).
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
    """Card 12744081: diesel, full (non-truncated) heading, mileage mil->km."""
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
    assert dto.mileage == 142950  # 14 295 mil * 10
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
    assert dto.mileage == 30870  # 3 087 mil * 10
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
    assert dto.mileage == 10  # 1 mil * 10
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
    assert dto.mileage == 56410  # 5 641 mil * 10


def test_diesel_card_with_truncated_heading_mileage_conversion() -> None:
    """Card 12744358: diesel, truncated heading, mileage 20 600 mil -> 206 000 km."""
    dtos = _by_id(parse_listing_cards(_load("volvo_xc60.html")))
    dto = dtos["12744358"]

    assert dto.make == "Volvo"
    assert dto.model == "XC60"
    assert dto.variant == "D4 AWD Summum VOC Varmare Dragkrok Skinn"
    assert dto.year == 2016
    assert dto.mileage == 206000  # 20 600 mil * 10
    assert dto.fuel_type == "Diesel"


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
