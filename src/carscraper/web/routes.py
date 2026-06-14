"""Page routes for the server-rendered dashboard.

Routes are thin: parse query params, call into `services/listings.py` for
data, and render a template with the result. No ORM queries or business
logic live here (see CLAUDE.md's "Layer responsibilities").
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from carscraper.db.session import get_session
from carscraper.services.listings import (
    ListingFilters,
    get_listing,
    list_car_listings,
    list_dealers_with_listings,
)
from carscraper.services.scrape_status import (
    get_run_log_entries,
    get_scrape_run,
    launch_all_dealers_scrape,
    launch_dealer_scrape,
    list_dealer_scrape_status,
)
from carscraper.services.stats import avg_price_per_model, price_history
from carscraper.services.tracked_models import (
    create_tracked_model,
    delete_tracked_model,
    list_tracked_models,
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


@router.get("/listings/{listing_id}", response_class=HTMLResponse)
def listing_detail(request: Request, listing_id: int) -> HTMLResponse:
    """Render the detail page for a single `CarListing`.

    Shows the listing's details plus a Chart.js line chart of its price
    history (`services.stats.price_history`). If the listing has no
    `PriceSnapshot` rows yet, the chart renders with an empty series and a
    "no price history yet" message instead of erroring.

    Returns a 404 if no listing with `listing_id` exists.
    """
    with get_session() as session:
        listing = get_listing(session, listing_id)
        if listing is None:
            raise HTTPException(status_code=404, detail="Listing not found")

        history = price_history(session, listing_id)

    chart_labels = [point.scraped_at.isoformat() for point in history]
    chart_prices = [point.price for point in history]

    return templates.TemplateResponse(
        request,
        "listing_detail.html",
        {
            "listing": listing,
            "history": history,
            "chart_labels": chart_labels,
            "chart_prices": chart_prices,
        },
    )


@router.get("/stats", response_class=HTMLResponse)
def stats_page(request: Request) -> HTMLResponse:
    """Render the stats summary page: average price per tracked model.

    With no active listings (or none with a price), renders an empty-state
    message instead of an empty table.
    """
    with get_session() as session:
        model_stats = avg_price_per_model(session)

    return templates.TemplateResponse(
        request,
        "stats.html",
        {"model_stats": model_stats},
    )


@router.get("/tracked-models", response_class=HTMLResponse)
def tracked_models_page(request: Request) -> HTMLResponse:
    """Render the tracked-models config page.

    Lists the currently configured `TrackedModel` rows and includes the
    add form. Removal is handled via the HTMX-driven list partial.
    """
    with get_session() as session:
        tracked_models = list_tracked_models(session)

    return templates.TemplateResponse(
        request,
        "tracked_models.html",
        {"tracked_models": tracked_models, "error": None},
    )


@router.post("/tracked-models", response_class=HTMLResponse)
def add_tracked_model(
    request: Request,
    make: str = Form(""),
    model: str = Form(""),
    variant: str = Form(""),
) -> HTMLResponse:
    """Add a new tracked model and re-render the tracked-models list partial.

    `make` and `model` are required; `variant` is optional. On validation
    failure, re-renders the list partial with an error message and without
    creating a row, so the HTMX swap can surface the error inline.
    """
    make = make.strip()
    model = model.strip()
    variant = variant.strip()

    error: str | None = None
    if not make or not model:
        error = "Make and model are required."

    with get_session() as session:
        if error is None:
            create_tracked_model(session, make=make, model=model, variant=variant or None)
        tracked_models = list_tracked_models(session)

    return templates.TemplateResponse(
        request,
        "partials/tracked_models_list.html",
        {"tracked_models": tracked_models, "error": error},
    )


@router.delete("/tracked-models/{tracked_model_id}", response_class=HTMLResponse)
def remove_tracked_model(request: Request, tracked_model_id: int) -> HTMLResponse:
    """Delete a tracked model and re-render the tracked-models list partial."""
    with get_session() as session:
        delete_tracked_model(session, tracked_model_id)
        tracked_models = list_tracked_models(session)

    return templates.TemplateResponse(
        request,
        "partials/tracked_models_list.html",
        {"tracked_models": tracked_models, "error": None},
    )


@router.get("/scrape", response_class=HTMLResponse)
def scrape_page(request: Request) -> HTMLResponse:
    """Render the scrape page: each dealer with its latest run status + controls.

    The dealer rows live in a partial that HTMX polls (see
    `scrape_dealers_status`) so a running scrape's spinner and the eventual
    success/failed status update without a manual reload.
    """
    with get_session() as session:
        dealer_statuses = list_dealer_scrape_status(session)

    return templates.TemplateResponse(
        request,
        "scrape.html",
        {"dealer_statuses": dealer_statuses},
    )


@router.get("/scrape/dealers", response_class=HTMLResponse)
def scrape_dealers_status(request: Request) -> HTMLResponse:
    """Render just the dealer-status list partial, for HTMX polling.

    Returns the same `scrape_dealers.html` partial the page embeds, so the
    poll can swap the list in place to reflect run progress/completion.
    """
    with get_session() as session:
        dealer_statuses = list_dealer_scrape_status(session)

    return templates.TemplateResponse(
        request,
        "partials/scrape_dealers.html",
        {"dealer_statuses": dealer_statuses},
    )


@router.post("/scrape/dealer/{dealer_id}", response_class=HTMLResponse)
async def trigger_dealer_scrape(request: Request, dealer_id: int) -> HTMLResponse:
    """Kick off a background scrape for one dealer and return the status list.

    The scrape runs in the background (its `ScrapeRun` row tracks progress);
    this returns immediately with the refreshed dealer-status partial, which
    HTMX polling then keeps up to date.
    """
    launch_dealer_scrape(dealer_id)

    with get_session() as session:
        dealer_statuses = list_dealer_scrape_status(session)

    return templates.TemplateResponse(
        request,
        "partials/scrape_dealers.html",
        {"dealer_statuses": dealer_statuses},
    )


@router.post("/scrape/all", response_class=HTMLResponse)
async def trigger_all_scrape(request: Request) -> HTMLResponse:
    """Kick off background scrapes for all enabled dealers; return status list."""
    launch_all_dealers_scrape()

    with get_session() as session:
        dealer_statuses = list_dealer_scrape_status(session)

    return templates.TemplateResponse(
        request,
        "partials/scrape_dealers.html",
        {"dealer_statuses": dealer_statuses},
    )


@router.get("/scrape/runs/{run_id}", response_class=HTMLResponse)
def scrape_run_report(request: Request, run_id: int) -> HTMLResponse:
    """Render a completed run's report: per-listing log entries + summary counts.

    Returns a 404 if no run with `run_id` exists. The log entries carry their
    related `CarListing` so the report can show make/model/url per change.
    """
    with get_session() as session:
        run = get_scrape_run(session, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Scrape run not found")

        log_entries = get_run_log_entries(session, run_id)

    return templates.TemplateResponse(
        request,
        "partials/scrape_report.html",
        {"run": run, "log_entries": log_entries},
    )
