"""Download a listing's images to local static storage (CAR-15).

This is the business-logic layer that turns the remote `image_urls` carried by
a `CarListingDTO` into locally-stored files plus `ListingImage` rows. Per
CLAUDE.md's "Layer responsibilities", it is the only place that both reaches
out over HTTP for image bytes and writes `ListingImage` rows — scrapers only
produce URLs, and the persistence service (CAR-12) calls in here once a
`CarListing` has been upserted.

Files land under::

    <static_root>/images/<dealer_slug>/<external_id>/<n>.<ext>

where `<static_root>` is `Settings.static_root` (the directory mounted at
``/static``), `<n>` is the image's 0-based carousel position, and `<ext>` is
inferred from the URL (defaulting to ``jpg``). The stored `ListingImage`
`local_path` is the path *relative to the static root* (forward-slashed), so
templates can build a ``/static/<local_path>`` URL directly.

**Idempotency.** Downloading is keyed on `(listing, position)`: a position
that already has a `ListingImage` row is skipped (no re-download, no duplicate
row). Re-running after a partial failure therefore only fetches the missing
positions. This is what lets CAR-12 call `download_listing_images` on every
scrape without re-fetching unchanged images.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.config import settings
from carscraper.db.models import CarListing, ListingImage

# Fallback extension when a URL doesn't carry a recognizable image suffix.
_DEFAULT_EXT = "jpg"
# Image extensions we accept from a URL's path; anything else falls back to
# `_DEFAULT_EXT` (dealers sometimes serve query-string'd or extension-less URLs).
_ALLOWED_EXTS = {"jpg", "jpeg", "png", "webp", "gif", "avif"}


def _extension_for(url: str) -> str:
    """Infer a file extension from an image URL's path.

    Returns a lowercase extension without the leading dot, falling back to
    `_DEFAULT_EXT` when the URL has no recognizable image suffix.
    """
    suffix = Path(urlparse(url).path).suffix.lstrip(".").lower()
    return suffix if suffix in _ALLOWED_EXTS else _DEFAULT_EXT


def _listing_image_dir(static_root: Path, dealer_slug: str, external_id: str) -> Path:
    """Directory holding one listing's downloaded images."""
    return static_root / "images" / dealer_slug / external_id


def _relative_path(static_root: Path, file_path: Path) -> str:
    """Path of `file_path` relative to the static root, forward-slashed."""
    return file_path.relative_to(static_root).as_posix()


def _existing_positions(session: Session, listing_id: int) -> set[int]:
    """Positions that already have a `ListingImage` row for the listing."""
    stmt = select(ListingImage.position).where(ListingImage.listing_id == listing_id)
    return set(session.execute(stmt).scalars())


def download_listing_images(
    session: Session,
    listing: CarListing,
    image_urls: list[str],
    *,
    client: httpx.Client | None = None,
) -> list[ListingImage]:
    """Download `image_urls` for `listing` and create `ListingImage` rows.

    The dealer slug used in the path is `listing.dealer.scraper_module`.
    Images are written to ``<static_root>/images/<slug>/<external_id>/<n>.<ext>``
    and a `ListingImage` row is added (not committed — the caller owns the
    transaction) for each newly-downloaded image.

    Idempotent: any image position that already has a `ListingImage` row is
    skipped, so a position is never re-downloaded and no duplicate rows are
    created. Returns the list of newly-created `ListingImage` rows (empty when
    there was nothing new to fetch).

    `client` lets callers (and tests) inject a configured/mocked
    `httpx.Client`; when omitted a short-lived client is created.
    """
    if not image_urls:
        return []

    static_root = settings.static_root
    dealer_slug = listing.dealer.scraper_module
    target_dir = _listing_image_dir(static_root, dealer_slug, listing.external_id)

    already = _existing_positions(session, listing.id)
    # Nothing new to do — every position is already recorded.
    if all(position in already for position in range(len(image_urls))):
        return []

    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    created: list[ListingImage] = []
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        for position, url in enumerate(image_urls):
            if position in already:
                continue

            response = client.get(url)
            response.raise_for_status()

            ext = _extension_for(url)
            file_path = target_dir / f"{position}.{ext}"
            file_path.write_bytes(response.content)

            image = ListingImage(
                listing_id=listing.id,
                local_path=_relative_path(static_root, file_path),
                position=position,
            )
            session.add(image)
            created.append(image)
    finally:
        if owns_client:
            client.close()

    return created
