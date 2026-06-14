"""Parsing for kvd.se auction entries into `CarListingDTO` (CAR-16).

`parse_auction` translates one raw `dict` from `api.fetch_car_auctions` (a
single entry from kvd.se's `auctions` response array) into a `CarListingDTO`,
per the field-mapping table in CAR-16. This is the normalization boundary
described in CLAUDE.md: every kvd.se-specific shape (nested
`processObject.properties`, `previewImages`, buy-now vs. preliminary pricing)
is translated here and nowhere else.

Parsing external data is a system boundary: if a raw entry is missing a field
`CarListingDTO` requires (`id`, `auctionUrl`, `brand`, or a derivable `model`),
`parse_auction` returns `None` rather than raising, and the caller
(`scraper.py`) skips/logs that entry.
"""

from __future__ import annotations

import logging

from carscraper.scrapers.base import CarListingDTO

logger = logging.getLogger(__name__)


def _properties(raw: dict) -> dict:
    """`processObject.properties`, or `{}` if either level is missing/null."""
    process_object = raw.get("processObject") or {}
    return process_object.get("properties") or {}


def _derive_model(properties: dict) -> str | None:
    """`familyName`, falling back to the first word of `modelName`.

    Returns `None` if neither yields a usable value.
    """
    family_name = properties.get("familyName")
    if family_name:
        return family_name

    model_name = properties.get("modelName")
    if model_name:
        first_word = model_name.split()[0] if model_name.split() else None
        if first_word:
            return first_word

    return None


def _derive_variant(properties: dict, model: str) -> str | None:
    """`modelName` with the `model` prefix stripped (case-insensitive).

    Returns `None` if `modelName` is missing or doesn't start with `model`.
    """
    model_name = properties.get("modelName")
    if not model_name:
        return None

    if not model_name.casefold().startswith(model.casefold()):
        return None

    variant = model_name[len(model) :].strip()
    return variant or None


def _derive_price(raw: dict) -> int | None:
    """`buyNowAmount` if buy-now is available, else `preliminaryPrice`."""
    if raw.get("buyNowAvailable") and raw.get("buyNowAmount") is not None:
        return raw["buyNowAmount"]
    return raw.get("preliminaryPrice")


def _derive_fuel_type(properties: dict) -> str | None:
    """First fuel's `fuelCode`, falling back to `electricType`."""
    fuels = properties.get("fuels") or []
    if fuels:
        fuel_code = fuels[0].get("fuelCode")
        if fuel_code:
            return fuel_code

    return properties.get("electricType")


def _derive_image_urls(raw: dict) -> list[str]:
    """`previewImages` sorted by `order` and mapped to `uri`.

    Falls back to a single-element list from `previewImage` if
    `previewImages` is absent/empty; otherwise `[]`.
    """
    preview_images = raw.get("previewImages")
    if preview_images:
        ordered = sorted(preview_images, key=lambda img: img.get("order", 0))
        return [img["uri"] for img in ordered if img.get("uri")]

    preview_image = raw.get("previewImage")
    if preview_image:
        return [preview_image]

    return []


def parse_auction(raw: dict) -> CarListingDTO | None:
    """Translate one raw kvd.se auction entry into a `CarListingDTO`.

    Returns `None` (and logs) if `id`, `auctionUrl`, `brand`, or a derivable
    `model` are missing from `raw` — these are the fields `CarListingDTO`
    requires, and a kvd.se entry missing one is treated as unparsable rather
    than raising.
    """
    auction_id = raw.get("id")
    auction_url = raw.get("auctionUrl")
    properties = _properties(raw)
    make = properties.get("brand")
    model = _derive_model(properties)

    if not auction_id or not auction_url or not make or not model:
        logger.warning(
            "Skipping kvd.se auction with missing required field(s): "
            "id=%r auctionUrl=%r brand=%r model=%r",
            auction_id,
            auction_url,
            make,
            model,
        )
        return None

    return CarListingDTO(
        external_id=str(auction_id),
        url=auction_url,
        make=make,
        model=model,
        variant=_derive_variant(properties, model),
        year=properties.get("modelYear"),
        mileage=properties.get("odometerReading"),
        price=_derive_price(raw),
        fuel_type=_derive_fuel_type(properties),
        transmission=properties.get("gearbox"),
        image_urls=_derive_image_urls(raw),
    )
