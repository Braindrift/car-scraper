"""Tests for the scrape interface page + background scrape plumbing (CAR-13).

Covers:
- `GET /scrape` rendering dealers with `last_scraped_at` ("never" when unset),
  and the empty state with zero dealers.
- The trigger endpoints (`POST /scrape/dealer/{id}`, `POST /scrape/all`)
  returning the dealer-status partial and launching background scrapes.
- The HTMX poll partial (`GET /scrape/dealers`) reflecting run status, including
  the running spinner.
- The run report (`GET /scrape/runs/{id}`): summary counts + per-listing log
  entries, plus 404 for an unknown run.
- The nav link to `/scrape`.

Background execution is exercised directly against the async service helpers
(`scrape_dealer_by_id` / `scrape_all_enabled_dealers`) with a registered test
scraper, since fire-and-forget `asyncio.create_task` work isn't deterministic
to await through `TestClient`. The route's job (schedule + return the partial)
is tested separately.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.db.models import Dealer, ScrapeRun, TrackedModel
from carscraper.db.session import Base, SessionLocal, create_db_engine
from carscraper.main import app
from carscraper.scrapers.base import BaseScraper, CarListingDTO, TrackedModelSpec
from carscraper.scrapers.registry import register
from carscraper.services.scrape_results import STATUS_SUCCESS
from carscraper.services.scrape_status import (
    list_dealer_scrape_status,
    scrape_all_enabled_dealers,
    scrape_dealer_by_id,
)

client = TestClient(app)

_SLUG = "test_web_scrape"
_NEXT_DTOS: list[CarListingDTO] = []


@register(_SLUG)
class _WebScraper(BaseScraper):
    async def scrape(self, tracked: list[TrackedModelSpec] | None = None) -> list[CarListingDTO]:
        return list(_NEXT_DTOS)


def _set_scrape(dtos: list[CarListingDTO]) -> None:
    global _NEXT_DTOS
    _NEXT_DTOS = dtos


@pytest.fixture(autouse=True)
def _reset_scraper() -> Generator[None, None, None]:
    _set_scrape([])
    yield
    _set_scrape([])


@pytest.fixture
def db_session(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    db_path = tmp_path / "web_scrape_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(SessionLocal, "kw", {**SessionLocal.kw, "bind": engine})

    with Session(engine) as session:
        yield session

    engine.dispose()


def _make_dealer(session: Session, name: str = "Test Dealer", slug: str = _SLUG) -> Dealer:
    dealer = Dealer(name=name, base_url="https://example.com", scraper_module=slug)
    session.add(dealer)
    session.commit()
    return dealer


def _track(session: Session, make: str, model: str) -> None:
    session.add(TrackedModel(make=make, model=model, variant=None))
    session.commit()


def _dto(external_id: str, *, price: int, make="Volvo", model="V70") -> CarListingDTO:
    return CarListingDTO(
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        make=make,
        model=model,
        price=price,
    )


# --- page rendering ---------------------------------------------------------


def test_scrape_page_empty_state(db_session: Session) -> None:
    response = client.get("/scrape")

    assert response.status_code == 200
    assert "No dealers configured yet." in response.text


def test_scrape_page_lists_dealers_never_scraped(db_session: Session) -> None:
    _make_dealer(db_session, name="Bilia Stockholm")

    response = client.get("/scrape")

    assert response.status_code == 200
    assert "Bilia Stockholm" in response.text
    assert "never" in response.text


def test_scrape_link_in_nav(db_session: Session) -> None:
    response = client.get("/scrape")

    assert response.status_code == 200
    assert '<a href="/scrape"' in response.text


# --- poll partial -----------------------------------------------------------


def test_scrape_dealers_partial_is_partial_only(db_session: Session) -> None:
    _make_dealer(db_session)

    response = client.get("/scrape/dealers")

    assert response.status_code == 200
    assert "Test Dealer" in response.text
    assert "<nav" not in response.text


def test_running_run_shows_spinner(db_session: Session) -> None:
    dealer = _make_dealer(db_session)
    db_session.add(ScrapeRun(dealer_id=dealer.id, status="running"))
    db_session.commit()

    response = client.get("/scrape/dealers")

    assert response.status_code == 200
    assert "Running" in response.text
    assert "animate-spin" in response.text


# --- trigger endpoints ------------------------------------------------------


def test_trigger_dealer_scrape_returns_partial(db_session: Session) -> None:
    dealer = _make_dealer(db_session)

    response = client.post(f"/scrape/dealer/{dealer.id}")

    assert response.status_code == 200
    assert "Test Dealer" in response.text
    assert "<nav" not in response.text


def test_trigger_all_scrape_returns_partial(db_session: Session) -> None:
    _make_dealer(db_session)

    response = client.post("/scrape/all")

    assert response.status_code == 200
    assert "Test Dealer" in response.text


# --- background scrape helpers (exercised directly) -------------------------


async def test_scrape_dealer_by_id_runs_and_persists(db_session: Session) -> None:
    dealer = _make_dealer(db_session)
    _track(db_session, "Volvo", "V70")
    _set_scrape([_dto("v70-1", price=189000)])

    await scrape_dealer_by_id(dealer.id)

    statuses = list_dealer_scrape_status(db_session)
    assert len(statuses) == 1
    run = statuses[0].latest_run
    assert run is not None
    assert run.status == STATUS_SUCCESS
    assert run.new_count == 1
    db_session.refresh(dealer)
    assert dealer.last_scraped_at is not None


async def test_scrape_dealer_by_id_missing_dealer_is_noop(db_session: Session) -> None:
    await scrape_dealer_by_id(9999)

    assert db_session.execute(select(ScrapeRun)).scalars().all() == []


async def test_scrape_all_enabled_dealers_runs_each(db_session: Session) -> None:
    _make_dealer(db_session, name="Dealer A", slug=_SLUG)
    # A disabled dealer should be skipped.
    disabled = Dealer(
        name="Dealer B",
        base_url="https://example.com",
        scraper_module="test_web_scrape_disabled",
        enabled=False,
    )
    db_session.add(disabled)
    db_session.commit()
    _track(db_session, "Volvo", "V70")
    _set_scrape([_dto("v70-1", price=189000)])

    await scrape_all_enabled_dealers()

    runs = db_session.execute(select(ScrapeRun)).scalars().all()
    # Only the enabled dealer ran.
    assert len(runs) == 1
    assert runs[0].status == STATUS_SUCCESS


# --- run report -------------------------------------------------------------


async def test_run_report_renders_summary_and_log(db_session: Session) -> None:
    dealer = _make_dealer(db_session)
    _track(db_session, "Volvo", "V70")
    _set_scrape([_dto("v70-1", price=189000)])
    await scrape_dealer_by_id(dealer.id)
    run = db_session.execute(select(ScrapeRun)).scalar_one()

    response = client.get(f"/scrape/runs/{run.id}")

    assert response.status_code == 200
    assert "scrape report" in response.text
    assert "new" in response.text
    assert "Volvo" in response.text
    assert "V70" in response.text


def test_run_report_not_found(db_session: Session) -> None:
    response = client.get("/scrape/runs/9999")

    assert response.status_code == 404
