"""Page routes for the server-rendered dashboard.

Routes are thin: parse query params, call into `services/listings.py` for
data, and render a template with the result. No ORM queries or business
logic live here (see CLAUDE.md's "Layer responsibilities").
"""

from __future__ import annotations

from fastapi import APIRouter, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse

from carscraper.db.session import get_session
from carscraper.services.listings import (
    ListingFilters,
    get_listing,
    list_car_listings,
    list_dealers_with_listings,
    listing_statuses,
    mark_listing_viewed,
    set_listing_discarded,
)
from carscraper.services.scrape_status import (
    get_run_log_entries,
    get_scrape_run,
    launch_all_dealers_scrape,
    launch_dealer_scrape,
    list_dealer_scrape_status,
)
from carscraper.services.stats import (
    MILEAGE_BUCKET_UNKNOWN,
    MILEAGE_BUCKETS,
    mileage_bucket_stats,
    model_overview_stats,
    price_history,
    year_bucket_stats,
)
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
    discarded: bool | None = None,
) -> ListingFilters:
    """Build `ListingFilters` from raw (string) query params.

    Query params arrive as strings (or `None`/empty string when an HTML
    form field is left blank); this normalizes those into the typed values
    `ListingFilters` expects, treating blank strings as "not set".

    `discarded` is not user-facing in the filter form — the route sets it to
    `False` for the main dashboard and `True` for the Discarded page.
    """
    return ListingFilters(
        make=make or None,
        model=model or None,
        dealer_id=int(dealer_id) if dealer_id else None,
        min_price=int(min_price) if min_price else None,
        max_price=int(max_price) if max_price else None,
        active_only=bool(active_only),
        discarded=discarded,
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
    filters = _parse_filters(
        make, model, dealer_id, min_price, max_price, active_only, discarded=False
    )

    with get_session() as session:
        listings = list_car_listings(session, filters)
        dealers = list_dealers_with_listings(session)
        statuses = listing_statuses(session, listings)

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "listings": listings,
            "dealers": dealers,
            "filters": filters,
            "statuses": statuses,
            "view": "active",
            "table_url": "/listings/table",
        },
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
    filters = _parse_filters(
        make, model, dealer_id, min_price, max_price, active_only, discarded=False
    )

    with get_session() as session:
        listings = list_car_listings(session, filters)
        statuses = listing_statuses(session, listings)

    return templates.TemplateResponse(
        request,
        "partials/listings_table.html",
        {"listings": listings, "statuses": statuses, "view": "active"},
    )


@router.get("/discarded", response_class=HTMLResponse)
def discarded_page(
    request: Request,
    make: str | None = None,
    model: str | None = None,
    dealer_id: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    active_only: str | None = None,
) -> HTMLResponse:
    """Render the Discarded page: listings the user has set aside.

    Same filter form and table as the dashboard, but scoped to discarded
    listings. Discarded entries are still scraped/updated and still count in
    stats — this is just a place to review/restore them.
    """
    filters = _parse_filters(
        make, model, dealer_id, min_price, max_price, active_only, discarded=True
    )

    with get_session() as session:
        listings = list_car_listings(session, filters)
        dealers = list_dealers_with_listings(session)
        statuses = listing_statuses(session, listings)

    return templates.TemplateResponse(
        request,
        "discarded.html",
        {
            "listings": listings,
            "dealers": dealers,
            "filters": filters,
            "statuses": statuses,
            "view": "discarded",
            "table_url": "/discarded/table",
        },
    )


@router.get("/discarded/table", response_class=HTMLResponse)
def discarded_table(
    request: Request,
    make: str | None = None,
    model: str | None = None,
    dealer_id: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    active_only: str | None = None,
) -> HTMLResponse:
    """Render just the discarded listings table partial, for the filter form."""
    filters = _parse_filters(
        make, model, dealer_id, min_price, max_price, active_only, discarded=True
    )

    with get_session() as session:
        listings = list_car_listings(session, filters)
        statuses = listing_statuses(session, listings)

    return templates.TemplateResponse(
        request,
        "partials/listings_table.html",
        {"listings": listings, "statuses": statuses, "view": "discarded"},
    )


@router.post("/listings/{listing_id}/discard")
def discard_listing(listing_id: int) -> Response:
    """Mark a listing discarded; tell HTMX to refresh the listings table.

    Returns 204 with an `HX-Trigger: refreshListings` header rather than
    re-rendering the table itself — the filter form listens for that event and
    re-fetches the table with the current filters applied, so the discarded row
    drops out without losing the user's filters.
    """
    with get_session() as session:
        set_listing_discarded(session, listing_id, discarded=True)

    return Response(status_code=204, headers={"HX-Trigger": "refreshListings"})


@router.post("/listings/{listing_id}/restore")
def restore_listing(listing_id: int) -> Response:
    """Restore a discarded listing; tell HTMX to refresh the listings table."""
    with get_session() as session:
        set_listing_discarded(session, listing_id, discarded=False)

    return Response(status_code=204, headers={"HX-Trigger": "refreshListings"})


@router.get("/listings/{listing_id}", response_class=HTMLResponse)
def listing_detail(request: Request, listing_id: int) -> HTMLResponse:
    """Render the detail page for a single `CarListing`.

    Shows the listing's details plus a Chart.js line chart of its price
    history (`services.stats.price_history`). If the listing has no
    `PriceSnapshot` rows yet, the chart renders with an empty series and a
    "no price history yet" message instead of erroring.

    Viewing a listing records `last_viewed_at = now()` (CAR-14), which clears
    its NEW/UPDATED badge on the next dashboard load.

    Returns a 404 if no listing with `listing_id` exists.
    """
    with get_session() as session:
        listing = get_listing(session, listing_id)
        if listing is None:
            raise HTTPException(status_code=404, detail="Listing not found")

        mark_listing_viewed(session, listing_id)
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
def stats_page(
    request: Request,
    make: str | None = None,
    model: str | None = None,
    include_inactive: str | None = None,
) -> HTMLResponse:
    """Render the stats summary page: per-(make, model) price overview.

    `make`/`model` (both optional) scope the overview to a single tracked
    model — set via the table's row links — with "All models" (no query
    params) showing every tracked model combined. `include_inactive`
    (checkbox, present/"true" when checked) toggles whether inactive
    listings are included; the default (unset) is active-only.

    With no matching listings (or none with a price), renders an empty-state
    message instead of an empty table.
    """
    make = make or None
    model = model or None
    show_inactive = bool(include_inactive)

    with get_session() as session:
        model_stats = model_overview_stats(
            session, make=make, model=model, include_inactive=show_inactive
        )
        year_stats = year_bucket_stats(
            session, make=make, model=model, include_inactive=show_inactive
        )
        mileage_stats = mileage_bucket_stats(
            session, make=make, model=model, include_inactive=show_inactive
        )

    year_labels = [str(row.year) if row.year is not None else "Unknown" for row in year_stats]
    year_counts = [row.listing_count for row in year_stats]
    year_price_ranges = [[row.min_price, row.max_price] for row in year_stats]

    mileage_labels = [row.bucket for row in mileage_stats]
    mileage_counts = [row.listing_count for row in mileage_stats]
    mileage_price_ranges = [[row.min_price, row.max_price] for row in mileage_stats]

    # Map each mileage bucket label to the `min_mileage`/`max_mileage`/
    # `mileage_unknown` drill-down params for CAR-22's chart onClick handler
    # (kept here so `MILEAGE_BUCKETS`/`MILEAGE_BUCKET_UNKNOWN` stay the single
    # source of truth for bucket boundaries).
    mileage_bucket_params: dict[str, dict[str, int | bool | None]] = {
        label: {"min_mileage": lower, "max_mileage": upper, "mileage_unknown": False}
        for label, lower, upper in MILEAGE_BUCKETS
    }
    mileage_bucket_params[MILEAGE_BUCKET_UNKNOWN] = {
        "min_mileage": None,
        "max_mileage": None,
        "mileage_unknown": True,
    }

    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "model_stats": model_stats,
            "make": make,
            "model": model,
            "include_inactive": show_inactive,
            "year_labels": year_labels,
            "year_counts": year_counts,
            "year_price_ranges": year_price_ranges,
            "mileage_labels": mileage_labels,
            "mileage_counts": mileage_counts,
            "mileage_price_ranges": mileage_price_ranges,
            "mileage_bucket_params": mileage_bucket_params,
        },
    )


@router.get("/stats/listings", response_class=HTMLResponse)
def stats_listings(
    request: Request,
    make: str | None = None,
    model: str | None = None,
    include_inactive: str | None = None,
    year: str | None = None,
    year_unknown: str | None = None,
    min_mileage: str | None = None,
    max_mileage: str | None = None,
    mileage_unknown: str | None = None,
) -> HTMLResponse:
    """Render a listings-table fragment for a clicked chart category (CAR-22).

    Drill-down target for the `/stats` distribution charts: clicking a year
    or mileage-bucket bar/category triggers an HTMX GET here with the same
    `make`/`model`/`include_inactive` scope as the chart plus either `year`
    (or `year_unknown=true` for the "Unknown" year bucket) or
    `min_mileage`/`max_mileage` (or `mileage_unknown=true` for the "Unknown"
    mileage bucket). Returns the same listings-table partial used elsewhere,
    plus a label describing the selected category for the results header.
    """
    make = make or None
    model = model or None
    show_inactive = bool(include_inactive)
    show_year_unknown = bool(year_unknown)
    show_mileage_unknown = bool(mileage_unknown)

    filters = ListingFilters(
        make=make,
        model=model,
        active_only=not show_inactive,
        year=int(year) if year else None,
        year_unknown=show_year_unknown,
        min_mileage=int(min_mileage) if min_mileage else None,
        max_mileage=int(max_mileage) if max_mileage else None,
        mileage_unknown=show_mileage_unknown,
    )

    if show_year_unknown:
        category_label = "Year: Unknown"
    elif year:
        category_label = f"Year: {year}"
    elif show_mileage_unknown:
        category_label = "Mileage: Unknown"
    elif min_mileage or max_mileage:
        if max_mileage is None:
            category_label = f"Mileage: {min_mileage}+ km"
        else:
            category_label = f"Mileage: {min_mileage}-{max_mileage} km"
    else:
        category_label = ""

    with get_session() as session:
        listings = list_car_listings(session, filters)
        statuses = listing_statuses(session, listings)

    return templates.TemplateResponse(
        request,
        "partials/stats_listings.html",
        {
            "listings": listings,
            "statuses": statuses,
            "view": "active",
            "category_label": category_label,
        },
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
