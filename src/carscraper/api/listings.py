"""JSON API router for `CarListing` resources (CAR-32).

Per CLAUDE.md, routers are thin: validate input, call a service, return a
response. No ORM queries or business logic live here.
"""

from __future__ import annotations

from fastapi import APIRouter, Response

from carscraper.db.session import get_session
from carscraper.services.listings import delete_car_listing

router = APIRouter(prefix="/api/listings", tags=["listings-api"])


@router.delete("/{listing_id}")
def delete_listing(listing_id: int) -> Response:
    """Permanently delete a single `CarListing` and all its associated data.

    Deletes the `CarListing` row, its `PriceSnapshot` rows, its
    `ListingImage` rows, and any on-disk image files. No `TrackedModel` is
    touched. Returns 200 with an empty body so HTMX performs the outerHTML
    swap (replacing the row with nothing, removing it from the DOM).
    """
    with get_session() as session:
        delete_car_listing(session, listing_id)

    return Response(content="", status_code=200)
