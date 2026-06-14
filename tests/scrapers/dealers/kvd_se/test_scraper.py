"""Tests for `KvdSeScraper.scrape()` and `fetch_car_auctions` pagination (CAR-16).

Uses `httpx.MockTransport` to serve the saved fixtures across pages: offset=0
-> `search_page_1.json` (4 entries), offset=20 -> `search_page_2.json` (3
entries), offset=40 -> `search_page_empty.json` (terminates pagination).
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from carscraper.scrapers.base import CarListingDTO
from carscraper.scrapers.dealers.kvd_se.api import API_URL, fetch_car_auctions
from carscraper.scrapers.dealers.kvd_se.scraper import KvdSeScraper
from carscraper.scrapers.registry import get_scraper_class, run_scraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


_PAGES_BY_OFFSET = {
    "0": _load("search_page_1.json"),
    "20": _load("search_page_2.json"),
    "40": _load("search_page_empty.json"),
}


def _handler(request: httpx.Request) -> httpx.Response:
    assert str(request.url).startswith(API_URL)
    offset = request.url.params.get("offset")
    assert offset in _PAGES_BY_OFFSET, f"Unexpected offset {offset!r} (would loop forever)"
    return httpx.Response(200, json=_PAGES_BY_OFFSET[offset])


# Captured before any monkeypatching of `httpx.AsyncClient` below, so
# `_mock_client` always constructs a real client (not a recursive mock).
_AsyncClient = httpx.AsyncClient


def _mock_client() -> httpx.AsyncClient:
    return _AsyncClient(transport=httpx.MockTransport(_handler))


def test_kvd_se_registered() -> None:
    assert get_scraper_class("kvd_se") is KvdSeScraper


async def test_fetch_car_auctions_paginates_until_empty_page() -> None:
    async with _mock_client() as client:
        auctions = await fetch_car_auctions(client)

    # 4 (page 1) + 3 (page 2), pagination stops at the empty page (offset=40).
    assert len(auctions) == 7
    ids = {a["id"] for a in auctions}
    assert "293977" in ids  # from page 1
    assert "293430" in ids  # from page 2


async def test_scrape_returns_parsed_dtos_dropping_unparsable_entries(monkeypatch) -> None:
    monkeypatch.setattr(
        "carscraper.scrapers.dealers.kvd_se.scraper.httpx.AsyncClient",
        lambda *a, **k: _mock_client(),
    )

    scraper = KvdSeScraper()
    listings = await scraper.scrape()

    assert len(listings) == 7
    assert all(isinstance(dto, CarListingDTO) for dto in listings)

    by_id = {dto.external_id: dto for dto in listings}
    assert by_id["293977"].make == "Porsche"
    assert by_id["293430"].make == "Ford"
    # Synthetic edge-case entries from page 2 also parse successfully.
    assert by_id["999001"].image_urls == []
    assert by_id["999002"].fuel_type == "Electric"


async def test_run_scraper_resolves_kvd_se_slug(monkeypatch) -> None:
    monkeypatch.setattr(
        "carscraper.scrapers.dealers.kvd_se.scraper.httpx.AsyncClient",
        lambda *a, **k: _mock_client(),
    )

    listings = await run_scraper("kvd_se")

    assert len(listings) == 7


@pytest.mark.parametrize("offset", ["0", "20"])
async def test_pages_have_expected_entry_counts(offset: str) -> None:
    page = _PAGES_BY_OFFSET[offset]
    expected = {"0": 4, "20": 3}[offset]
    assert len(page["auctions"]) == expected
