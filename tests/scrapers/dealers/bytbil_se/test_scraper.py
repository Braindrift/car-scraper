"""Tests for `BytbilSeScraper.scrape()` and `fetch_search_pages` (CAR-26).

Uses ``httpx.MockTransport`` keyed by query-string parameters to simulate
bytbil.se's paginated search API:

- ``Makes=Volvo&Models=XC60&...&Page=1`` → 200 with ``fixtures/volvo_xc60.html``
- ``Makes=Volvo&Models=XC60&...&Page=2`` → 404 (end of results)
- ``Makes=DoesNotExist&...&Page=1`` → 404

This covers the "stop on 404", "stop on empty page", "dedupe by external_id",
and "empty tracked → []" paths.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from carscraper.scrapers.base import CarListingDTO, TrackedModelSpec
from carscraper.scrapers.dealers.bytbil_se.api import fetch_search_pages
from carscraper.scrapers.dealers.bytbil_se.scraper import BytbilSeScraper
from carscraper.scrapers.registry import get_scraper_class, run_scraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


_FIXTURE_XC60 = _load("volvo_xc60.html")

# Empty result page — has the result-list markup but no li.result-list-item.
_EMPTY_PAGE = "<html><body><ul class='result-list uk-padding-remove'></ul></body></html>"


def _handler(request: httpx.Request) -> httpx.Response:
    qs = parse_qs(urlparse(str(request.url)).query)
    make = qs.get("Makes", [""])[0]
    model = qs.get("Models", [""])[0]
    page = int(qs.get("Page", ["1"])[0])

    if make == "Volvo" and model == "XC60":
        if page == 1:
            return httpx.Response(200, html=_FIXTURE_XC60)
        # Page 2 returns 404 — normal end-of-results signal.
        return httpx.Response(404, text="not found")

    if make == "EmptyMake" and model == "EmptyModel":
        return httpx.Response(200, html=_EMPTY_PAGE)

    return httpx.Response(404, text="not found")


# Capture the real AsyncClient before any monkeypatching so `_mock_client()`
# doesn't recurse when the scraper module's `httpx.AsyncClient` is replaced.
_RealAsyncClient = httpx.AsyncClient


def _mock_client() -> httpx.AsyncClient:
    return _RealAsyncClient(transport=httpx.MockTransport(_handler), follow_redirects=True)


# --- registry -----------------------------------------------------------------


def test_bytbil_se_registered() -> None:
    assert get_scraper_class("bytbil_se") is BytbilSeScraper


# --- BytbilSeScraper.scrape ---------------------------------------------------


async def test_scrape_with_none_tracked_returns_empty() -> None:
    scraper = BytbilSeScraper()
    assert await scraper.scrape(None) == []


async def test_scrape_with_empty_tracked_returns_empty() -> None:
    scraper = BytbilSeScraper()
    assert await scraper.scrape([]) == []


async def test_scrape_returns_parsed_dtos(monkeypatch) -> None:
    monkeypatch.setattr(
        "carscraper.scrapers.dealers.bytbil_se.scraper.httpx.AsyncClient",
        lambda *a, **k: _mock_client(),
    )

    scraper = BytbilSeScraper()
    tracked = [TrackedModelSpec(make="Volvo", model="XC60")]
    listings = await scraper.scrape(tracked)

    assert len(listings) == 3
    assert all(isinstance(dto, CarListingDTO) for dto in listings)
    ids = {dto.external_id for dto in listings}
    assert ids == {"19217540", "19217474", "19215626"}


async def test_scrape_dedupes_by_external_id(monkeypatch) -> None:
    """Two TrackedModelSpecs for the same (make, model) → only one set of listings."""
    monkeypatch.setattr(
        "carscraper.scrapers.dealers.bytbil_se.scraper.httpx.AsyncClient",
        lambda *a, **k: _mock_client(),
    )

    scraper = BytbilSeScraper()
    tracked = [
        TrackedModelSpec(make="Volvo", model="XC60", variant="T6"),
        TrackedModelSpec(make="volvo", model="xc60", variant="D4"),  # same, different case
    ]
    listings = await scraper.scrape(tracked)

    assert len(listings) == 3
    assert len({dto.external_id for dto in listings}) == 3


# --- fetch_search_pages -------------------------------------------------------


async def test_fetch_search_pages_stops_on_404() -> None:
    """Page 1 returns results, page 2 returns 404 → only page 1 fetched."""
    tracked = [TrackedModelSpec(make="Volvo", model="XC60")]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    assert len(pages) == 1
    html, make, model = pages[0]
    assert make == "Volvo"
    assert model == "XC60"
    assert "result-list-item" in html


async def test_fetch_search_pages_stops_on_empty_page() -> None:
    """A page with no listing cards → treated as end-of-results (not an error)."""
    tracked = [TrackedModelSpec(make="EmptyMake", model="EmptyModel")]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    assert pages == []


async def test_fetch_search_pages_skips_unknown_make_model() -> None:
    tracked = [TrackedModelSpec(make="DoesNotExist", model="Nope")]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    assert pages == []


async def test_fetch_search_pages_dedupes_same_make_model() -> None:
    """Two specs for the same (make, model) only trigger one paginated run."""
    tracked = [
        TrackedModelSpec(make="Volvo", model="XC60", variant="T6"),
        TrackedModelSpec(make="Volvo", model="XC60", variant="D4"),
    ]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    assert len(pages) == 1


# --- run_scraper integration --------------------------------------------------


@pytest.mark.parametrize("tracked", [None, []])
async def test_run_scraper_with_no_tracked_models_returns_empty(tracked) -> None:
    assert await run_scraper("bytbil_se", tracked) == []
