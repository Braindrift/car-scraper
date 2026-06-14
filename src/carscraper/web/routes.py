"""Page routes for the server-rendered dashboard.

Renders templates only — no business logic. Once `services/` exposes
listing data, this module will fetch it via a service call and pass it to
the template context.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from carscraper.web.templating import templates

router = APIRouter(tags=["web"])


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    """Render the dashboard page.

    Currently always renders the empty state; later tickets will pass real
    listing/stat data into the template context.
    """
    return templates.TemplateResponse(request, "dashboard.html")
