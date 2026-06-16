"""Validation tests for `CarListingDTO`, `BaseScraper`, and `is_leasing_dto`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from carscraper.scrapers.base import BaseScraper, CarListingDTO, is_leasing_dto


def test_car_listing_dto_minimal_required_fields() -> None:
    dto = CarListingDTO(
        external_id="123",
        url="https://example.com/listings/123",
        make="Volvo",
        model="V70",
    )

    assert dto.external_id == "123"
    assert dto.url == "https://example.com/listings/123"
    assert dto.make == "Volvo"
    assert dto.model == "V70"
    # Optional fields default to None.
    assert dto.variant is None
    assert dto.year is None
    assert dto.mileage is None
    assert dto.price is None
    assert dto.fuel_type is None
    assert dto.transmission is None


def test_car_listing_dto_full() -> None:
    dto = CarListingDTO(
        external_id="123",
        url="https://example.com/listings/123",
        make="Volvo",
        model="V70",
        variant="T5",
        year=2018,
        mileage=85000,
        price=189000,
        fuel_type="Petrol",
        transmission="Automatic",
    )

    assert dto.variant == "T5"
    assert dto.year == 2018
    assert dto.mileage == 85000
    assert dto.price == 189000
    assert dto.fuel_type == "Petrol"
    assert dto.transmission == "Automatic"


@pytest.mark.parametrize("missing_field", ["external_id", "url", "make", "model"])
def test_car_listing_dto_requires_core_fields(missing_field: str) -> None:
    fields = {
        "external_id": "123",
        "url": "https://example.com/listings/123",
        "make": "Volvo",
        "model": "V70",
    }
    del fields[missing_field]

    with pytest.raises(ValidationError):
        CarListingDTO(**fields)


@pytest.mark.parametrize("missing_field", ["external_id", "url", "make", "model"])
def test_car_listing_dto_rejects_empty_core_fields(missing_field: str) -> None:
    fields = {
        "external_id": "123",
        "url": "https://example.com/listings/123",
        "make": "Volvo",
        "model": "V70",
    }
    fields[missing_field] = ""

    with pytest.raises(ValidationError):
        CarListingDTO(**fields)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("year", "not-a-year"),
        ("mileage", "not-a-mileage"),
        ("price", "not-a-price"),
    ],
)
def test_car_listing_dto_rejects_invalid_numeric_fields(field: str, value: str) -> None:
    fields = {
        "external_id": "123",
        "url": "https://example.com/listings/123",
        "make": "Volvo",
        "model": "V70",
        field: value,
    }

    with pytest.raises(ValidationError):
        CarListingDTO(**fields)


def test_base_scraper_cannot_be_instantiated_directly() -> None:
    with pytest.raises(TypeError):
        BaseScraper()  # type: ignore[abstract]


def test_base_scraper_subclass_must_implement_scrape() -> None:
    class IncompleteScraper(BaseScraper):
        pass

    with pytest.raises(TypeError):
        IncompleteScraper()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# is_leasing_dto — CAR-30
# ---------------------------------------------------------------------------


def _dto(**kwargs) -> CarListingDTO:
    """Construct a minimal `CarListingDTO` with optional field overrides."""
    base = {
        "external_id": "1",
        "url": "https://example.com/1",
        "make": "Volvo",
        "model": "V60",
    }
    base.update(kwargs)
    return CarListingDTO(**base)


# -- positive cases: leasing detected ----------------------------------------


@pytest.mark.parametrize(
    "raw_price_text",
    [
        "2 450 kr/mån",
        "3 990 KR/MÅN",  # uppercase variant
        "2450 kr/man",  # ASCII fallback (encoding mishap)
        "1 995 per månad",
        "1 995 per manad",  # ASCII fallback
        "Leasing 2 990 kr",
        "leasing",
        "LEASING",
    ],
)
def test_is_leasing_dto_detects_price_text_keywords(raw_price_text: str) -> None:
    dto = _dto(raw_price_text=raw_price_text, price=None)
    assert is_leasing_dto(dto) is True


@pytest.mark.parametrize(
    "variant",
    [
        "Leasing Edition",
        "T6 leasing special",
        "LEASING",
    ],
)
def test_is_leasing_dto_detects_variant_keywords(variant: str) -> None:
    dto = _dto(variant=variant)
    assert is_leasing_dto(dto) is True


# -- negative cases: normal for-sale listings ---------------------------------


@pytest.mark.parametrize(
    "raw_price_text",
    [
        "439 700 kr",
        "189 000 kr",
        None,
        "",
    ],
)
def test_is_leasing_dto_passes_normal_price_text(raw_price_text: str | None) -> None:
    dto = _dto(raw_price_text=raw_price_text, price=439700)
    assert is_leasing_dto(dto) is False


def test_is_leasing_dto_passes_normal_variant() -> None:
    dto = _dto(variant="T6 AWD Core")
    assert is_leasing_dto(dto) is False


def test_is_leasing_dto_passes_no_price_text_no_variant() -> None:
    dto = _dto()
    assert is_leasing_dto(dto) is False
