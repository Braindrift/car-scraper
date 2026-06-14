"""Smoke tests for the placeholder `listings`/`dealers`/`config`/`stats` routers.

Confirms each router is wired into `app` and returns an empty list, per
CAR-4's "real/placeholder but not dead code" scope.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from carscraper.main import app

client = TestClient(app)


@pytest.mark.parametrize(
    "path",
    [
        "/listings",
        "/dealers",
        "/config/tracked-models",
        "/stats/avg-price-per-model",
    ],
)
def test_placeholder_routes_return_empty_list(path: str) -> None:
    response = client.get(path)

    assert response.status_code == 200
    assert response.json() == []
