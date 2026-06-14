"""Page routes for the server-rendered dashboard.

Routes are thin: parse query params, call into `services/listings.py` for
data, and render a template with the result. No ORM queries or business
logic live here (see CLAUDE.md's "Layer responsibilities").
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from carscraper.db.session import get_session
from carscraper.services.listings import (
    ListingFilters,
    list_car_listings,
    list_dealers_with_listings,
)
from carscraper.web.templating import templates

router = APIRouter(tags=["web"])


def _parse_filters(
    make: str | None,
    model: str | None,
    dealer_id: str | None,
    min_price: str | None,
    max_price: str | None,
    active_only: str | None,
) -> ListingFilters:
    """Build `ListingFilters` from raw (string) query params.

    Query params arrive as strings (or `None`/empty string when an HTML
    form field is left blank); this normalizes those into the typed values
    `ListingFilters` expects, treating blank strings as "not set".
    """
    return ListingFilters(
        make=make or None,
        model=model or None,
        dealer_id=int(dealer_id) if dealer_id else None,
        min_price=int(min_price) if min_price else None,
        max_price=int(max_price) if max_price else None,
        active_only=bool(active_only),
    )


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    make: str | None = None,
    model: str | None = None,
    dealer_id: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    active_only: str | None = None,
) -> HTMLResponse:
    """Render the dashboard page: filter form + listings table.

    With no listings in the database, the table renders the same empty
    state as before CAR-6. Query params (mirroring the filter form's
    fields) are applied via `services.listings.list_car_listings` and also
    reflected back into the form so the page can be linked/bookmarked with
    filters applied.
    """
    filters = _parse_filters(make, model, dealer_id, min_price, max_price, active_only)

    with get_session() as session:
        listings = list_car_listings(session, filters)
        dealers = list_dealers_with_listings(session)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"listings": listings, "dealers": dealers, "filters": filters},
    )


@router.get("/listings/table", response_class=HTMLResponse)
def listings_table(
    request: Request,
    make: str | None = None,
    model: str | None = None,
    dealer_id: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    active_only: str | None = None,
) -> HTMLResponse:
    """Render just the listings table partial, for the HTMX filter form.

    Returns the same `listings_table.html` partial used by `dashboard()`,
    so the filter form can swap `#listings-table`'s contents without a full
    page reload.
    """
    filters = _parse_filters(make, model, dealer_id, min_price, max_price, active_only)

    with get_session() as session:
        listings = list_car_listings(session, filters)

    return templates.TemplateResponse(
        request,
        "partials/listings_table.html",
        {"listings": listings},
    )
