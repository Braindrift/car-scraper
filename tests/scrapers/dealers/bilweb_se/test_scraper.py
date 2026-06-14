"""Tests for `BilwebSeScraper.scrape()` and `fetch_search_pages` (CAR-18).

Uses `httpx.MockTransport` keyed by request path: `/sok/peugeot/5008` ->
`fixtures/peugeot_5008.html`, `/sok/volvo/xc60` -> `fixtures/volvo_xc60.html`.
Any other path responds 404 (covers the "non-200 page is skipped" path).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from carscraper.scrapers.base import CarListingDTO, TrackedModelSpec
from carscraper.scrapers.dealers.bilweb_se.api import fetch_search_pages
from carscraper.scrapers.dealers.bilweb_se.scraper import BilwebSeScraper
from carscraper.scrapers.registry import get_scraper_class, run_scraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


_PAGES_BY_PATH = {
    "/sok/peugeot/5008": _load("peugeot_5008.html"),
    "/sok/volvo/xc60": _load("volvo_xc60.html"),
}

# A 301 redirect, as bilweb.se issues for "/sok/mercedes-benz" -> "/sok/mercedes".
_REDIRECTS = {
    "/sok/mercedes-benz/c-klass": "/sok/mercedes/c-klass",
}


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path

    if path in _REDIRECTS:
        return httpx.Response(301, headers={"location": _REDIRECTS[path]})

    if path == "/sok/mercedes/c-klass":
        return httpx.Response(200, html=_PAGES_BY_PATH["/sok/peugeot/5008"])

    if path in _PAGES_BY_PATH:
        return httpx.Response(200, html=_PAGES_BY_PATH[path])

    if path == "/sok/empty/model":
        return httpx.Response(200, html="<html><body><div id='vehicle_card'></div></body></html>")

    return httpx.Response(404, text="not found")


_AsyncClient = httpx.AsyncClient


def _mock_client() -> httpx.AsyncClient:
    return _AsyncClient(transport=httpx.MockTransport(_handler), follow_redirects=True)


def test_bilweb_se_registered() -> None:
    assert get_scraper_class("bilweb_se") is BilwebSeScraper


# --- fetch_search_pages -------------------------------------------------------


async def test_fetch_search_pages_returns_html_for_tracked_models() -> None:
    tracked = [
        TrackedModelSpec(make="Peugeot", model="5008"),
        TrackedModelSpec(make="Volvo", model="XC60"),
    ]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    assert len(pages) == 2


async def test_fetch_search_pages_dedupes_same_make_model() -> None:
    """Two `TrackedModelSpec`s for the same (make, model) -> one page fetched."""
    tracked = [
        TrackedModelSpec(make="Peugeot", model="5008", variant="GT"),
        TrackedModelSpec(make="peugeot", model="5008", variant="Allure"),
    ]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    assert len(pages) == 1


async def test_fetch_search_pages_skips_404_page() -> None:
    tracked = [
        TrackedModelSpec(make="Volvo", model="XC60"),
        TrackedModelSpec(make="DoesNotExist", model="Nope"),
    ]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    # Only the Volvo XC60 page is returned; the unknown make/model is skipped.
    assert len(pages) == 1


async def test_fetch_search_pages_skips_empty_card_page() -> None:
    tracked = [TrackedModelSpec(make="Empty", model="Model")]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    assert pages == []


async def test_fetch_search_pages_follows_redirect() -> None:
    """ "mercedes-benz" 301-redirects to "mercedes" (handled by follow_redirects)."""
    tracked = [TrackedModelSpec(make="Mercedes-Benz", model="C-Klass")]
    async with _mock_client() as client:
        pages = await fetch_search_pages(client, tracked)

    assert len(pages) == 1


# --- BilwebSeScraper.scrape ----------------------------------------------------


async def test_scrape_with_no_tracked_models_returns_empty() -> None:
    scraper = BilwebSeScraper()

    assert await scraper.scrape(None) == []
    assert await scraper.scrape([]) == []


async def test_scrape_returns_parsed_dtos(monkeypatch) -> None:
    monkeypatch.setattr(
        "carscraper.scrapers.dealers.bilweb_se.scraper.httpx.AsyncClient",
        lambda *a, **k: _mock_client(),
    )

    scraper = BilwebSeScraper()
    tracked = [
        TrackedModelSpec(make="Peugeot", model="5008"),
        TrackedModelSpec(make="Volvo", model="XC60"),
    ]
    listings = await scraper.scrape(tracked)

    assert len(listings) == 5  # 3 from peugeot_5008 + 2 from volvo_xc60
    assert all(isinstance(dto, CarListingDTO) for dto in listings)
    by_id = {dto.external_id: dto for dto in listings}
    assert by_id["12744081"].make == "Peugeot"
    assert by_id["12744358"].make == "Volvo"


async def test_scrape_dedupes_by_external_id(monkeypatch) -> None:
    """Two tracked specs resolving to the same page don't duplicate listings."""
    monkeypatch.setattr(
        "carscraper.scrapers.dealers.bilweb_se.scraper.httpx.AsyncClient",
        lambda *a, **k: _mock_client(),
    )

    scraper = BilwebSeScraper()
    tracked = [
        TrackedModelSpec(make="Peugeot", model="5008", variant="GT"),
        TrackedModelSpec(make="Peugeot", model="5008", variant="Allure"),
    ]
    listings = await scraper.scrape(tracked)

    assert len(listings) == 3
    assert len({dto.external_id for dto in listings}) == 3


async def test_run_scraper_resolves_bilweb_se_slug(monkeypatch) -> None:
    monkeypatch.setattr(
        "carscraper.scrapers.dealers.bilweb_se.scraper.httpx.AsyncClient",
        lambda *a, **k: _mock_client(),
    )

    listings = await run_scraper("bilweb_se", [TrackedModelSpec(make="Volvo", model="XC60")])

    assert len(listings) == 2


@pytest.mark.parametrize("tracked", [None, []])
async def test_run_scraper_with_no_tracked_models_returns_empty(tracked) -> None:
    assert await run_scraper("bilweb_se", tracked) == []
