"""Tests for the dashboard route (`GET /`).

Covers CAR-5's Definition of Done: the route renders the base layout
extended by the empty-state dashboard, and includes the Tailwind/HTMX/
Chart.js script tags.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from carscraper.main import app

client = TestClient(app)


def test_dashboard_returns_200_with_empty_state() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "No listings yet — run a scrape to get started." in response.text


def test_dashboard_includes_frontend_dependencies() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert "cdn.tailwindcss.com" in response.text
    assert "htmx.org" in response.text
    assert "chart.js" in response.text.lower()
