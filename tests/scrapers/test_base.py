"""Validation tests for `CarListingDTO` and `BaseScraper`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from carscraper.scrapers.base import BaseScraper, CarListingDTO


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
