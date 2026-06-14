"""Tests for `parse_auction`'s field mapping (CAR-16).

Exercises the field-mapping table from CAR-16 against fixture entries from
`fixtures/search_page_1.json` (real, captured) and
`fixtures/search_page_2.json` (one real entry plus hand-constructed synthetic
entries for edge cases not found live: no `previewImages`, and an EV with no
`buyNowAmount`/empty `fuels`).
"""

from __future__ import annotations

import json
from pathlib import Path

from carscraper.scrapers.base import CarListingDTO
from carscraper.scrapers.dealers.kvd_se.parse import parse_auction

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def _auction(fixture: str, auction_id: str) -> dict:
    data = _load(fixture)
    for auction in data["auctions"]:
        if auction["id"] == auction_id:
            return auction
    raise AssertionError(f"No auction with id {auction_id!r} in {fixture}")


def test_parse_auction_normal_entry_with_buy_now() -> None:
    """KIA Niro: buyNowAvailable + buyNowAmount -> price is buyNowAmount."""
    dto = parse_auction(_auction("search_page_1.json", "293910"))

    assert dto == CarListingDTO(
        external_id="293910",
        url="https://www.kvd.se/fast-pris/kia-niro-plug-in-hybrid-1-6-141hk-293910",
        make="KIA",
        model="Niro",
        variant="Plug-in Hybrid 1.6 (141hk)",
        year=2021,
        mileage=65000,
        price=223800,
        fuel_type="Petrol",
        transmission="Automatic",
        image_urls=[
            "https://kvdbil-images.imgix.net/7280874/57c78083.jpg",
            "https://kvdbil-images.imgix.net/7280874/e33a44a7.jpg",
        ],
    )


def test_parse_auction_price_falls_back_to_preliminary_price() -> None:
    """Porsche Taycan: buyNowAvailable=false -> price is preliminaryPrice,
    even though buyNowAmount is also set."""
    dto = parse_auction(_auction("search_page_1.json", "293977"))

    assert dto is not None
    assert dto.price == 1100000
    assert dto.model == "Taycan"
    assert dto.variant == "4 Cross Turismo (435hk)"
    assert dto.fuel_type == "Electric"
    assert dto.transmission == "Automatic"


def test_parse_auction_price_falls_back_when_buy_now_amount_is_null() -> None:
    """KIA Soul: buyNowAvailable=false and buyNowAmount=null -> preliminaryPrice."""
    dto = parse_auction(_auction("search_page_1.json", "293855"))

    assert dto is not None
    assert dto.price == 130000
    assert dto.model == "Soul"
    assert dto.variant == "EV (110hk)"
    assert dto.fuel_type == "Electric"


def test_parse_auction_variant_is_none_when_model_name_lacks_family_prefix() -> None:
    """Mercedes A-Klass: modelName "A 250 e 8G-DCT 218hk" doesn't start with
    familyName "A-Klass" -> variant is None, model is still "A-Klass"."""
    dto = parse_auction(_auction("search_page_1.json", "293659"))

    assert dto is not None
    assert dto.make == "Mercedes"
    assert dto.model == "A-Klass"
    assert dto.variant is None
    assert dto.price == 224800


def test_parse_auction_image_ordering() -> None:
    """previewImages are mapped to image_urls sorted by `order`."""
    dto = parse_auction(_auction("search_page_2.json", "293430"))

    assert dto is not None
    assert dto.image_urls == [
        "https://kvdbil-images.imgix.net/7280498/d6a4411f.jpg",
        "https://kvdbil-images.imgix.net/7280498/026786b1.jpg",
    ]


def test_parse_auction_no_preview_images_yields_empty_image_urls() -> None:
    """Synthetic entry with no `previewImages` and no `previewImage` -> []."""
    dto = parse_auction(_auction("search_page_2.json", "999001"))

    assert dto is not None
    assert dto.model == "Corolla"
    assert dto.variant == "1.8 Hybrid (122hk)"
    assert dto.price == 99900
    assert dto.image_urls == []


def test_parse_auction_ev_falls_back_to_electric_type_and_preview_image() -> None:
    """Synthetic EV entry: empty `fuels` -> fuel_type from electricType;
    no buyNowAmount -> price from preliminaryPrice; falls back to
    `previewImage` (singular) for image_urls."""
    dto = parse_auction(_auction("search_page_2.json", "999002"))

    assert dto is not None
    assert dto.make == "Polestar"
    assert dto.model == "2"
    assert dto.variant == "Long Range Single Motor"
    assert dto.price == 415000
    assert dto.fuel_type == "Electric"
    assert dto.image_urls == ["https://kvdbil-images.imgix.net/8000002/cover.jpg"]


def test_parse_auction_returns_none_when_brand_missing() -> None:
    raw = {
        "id": "1",
        "auctionUrl": "https://www.kvd.se/example-1",
        "processObject": {"properties": {"familyName": "Focus", "modelName": "Focus"}},
    }

    assert parse_auction(raw) is None


def test_parse_auction_returns_none_when_id_missing() -> None:
    raw = {
        "auctionUrl": "https://www.kvd.se/example-2",
        "processObject": {"properties": {"brand": "Ford", "familyName": "Focus"}},
    }

    assert parse_auction(raw) is None


def test_parse_auction_returns_none_when_model_undeliverable() -> None:
    """No `familyName` and `modelName` is missing/empty -> model can't be derived."""
    raw = {
        "id": "3",
        "auctionUrl": "https://www.kvd.se/example-3",
        "processObject": {"properties": {"brand": "Ford"}},
    }

    assert parse_auction(raw) is None


def test_parse_auction_derives_model_from_model_name_when_family_name_missing() -> None:
    """No `familyName` -> model falls back to the first word of `modelName`."""
    raw = {
        "id": "4",
        "auctionUrl": "https://www.kvd.se/example-4",
        "buyNowAmount": 100000,
        "buyNowAvailable": True,
        "processObject": {
            "properties": {
                "brand": "Saab",
                "modelName": "9-3 Aero 2.0T",
                "gearbox": "Manual",
            }
        },
    }

    dto = parse_auction(raw)

    assert dto is not None
    assert dto.model == "9-3"
    assert dto.variant == "Aero 2.0T"
