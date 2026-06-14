"""Tests for `services.scrape_runner.run_enabled_dealers`."""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import Dealer
from carscraper.db.session import Base, create_db_engine
from carscraper.services.scrape_runner import run_enabled_dealers
from tests.scrapers.dummy import DUMMY_LISTINGS


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    db_path = tmp_path / "scrape_runner_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


async def test_zero_dealers_configured_reports_zero(session: Session) -> None:
    result = await run_enabled_dealers(session)

    assert result.dealers_scraped == 0
    assert result.listings == []


async def test_enabled_dealer_is_scraped(session: Session) -> None:
    session.add(
        Dealer(
            name="Dummy Dealer",
            base_url="https://example.com",
            scraper_module="dummy",
        )
    )
    session.commit()

    result = await run_enabled_dealers(session)

    assert result.dealers_scraped == 1
    assert result.listings == DUMMY_LISTINGS


async def test_disabled_dealer_is_not_scraped(session: Session) -> None:
    session.add(
        Dealer(
            name="Dummy Dealer",
            base_url="https://example.com",
            scraper_module="dummy",
            enabled=False,
        )
    )
    session.commit()

    result = await run_enabled_dealers(session)

    assert result.dealers_scraped == 0
    assert result.listings == []


async def test_dealer_slug_filter(session: Session) -> None:
    session.add(
        Dealer(
            name="Dummy Dealer",
            base_url="https://example.com",
            scraper_module="dummy",
        )
    )
    session.commit()

    result = await run_enabled_dealers(session, dealer_slug="does-not-exist")

    assert result.dealers_scraped == 0
    assert result.listings == []
