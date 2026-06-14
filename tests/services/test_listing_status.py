"""Tests for the dashboard status-derivation logic in `services.listings` (CAR-14).

Covers `listing_statuses` for each case (NEW / UPDATED / SEEN) and
`mark_listing_viewed` recording `last_viewed_at` so a listing reads as SEEN
afterwards. Exercised against a seeded temporary SQLite database.
"""

from __future__ import annotations

from collections.abc import Generator
from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from carscraper.db.models import (
    CarListing,
    Dealer,
    ScrapeLogEntry,
    ScrapeRun,
)
from carscraper.db.session import Base, create_db_engine
from carscraper.services.listings import (
    STATUS_NEW,
    STATUS_SEEN,
    STATUS_UPDATED,
    list_car_listings,
    listing_statuses,
    mark_listing_viewed,
)
from carscraper.services.scrape_results import CHANGE_UPDATED, STATUS_SUCCESS

# A fixed timeline so "before"/"after" comparisons are unambiguous.
_BASE = datetime(2026, 6, 1, 12, 0, 0)


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    db_path = tmp_path / "listing_status_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        yield session

    engine.dispose()


@pytest.fixture
def dealer(session: Session) -> Dealer:
    dealer = Dealer(name="Bilia", base_url="https://bilia.example", scraper_module="bilia")
    session.add(dealer)
    session.commit()
    return dealer


def _add_listing(
    session: Session,
    dealer: Dealer,
    external_id: str,
    *,
    first_seen: datetime,
    last_seen: datetime,
    last_viewed_at: datetime | None,
) -> CarListing:
    listing = CarListing(
        dealer_id=dealer.id,
        external_id=external_id,
        url=f"https://bilia.example/{external_id}",
        make="Volvo",
        model="V70",
        price=150_000,
        first_seen=first_seen,
        last_seen=last_seen,
        last_viewed_at=last_viewed_at,
        active=True,
    )
    session.add(listing)
    session.commit()
    return listing


def _add_updated_log(
    session: Session,
    dealer: Dealer,
    listing: CarListing,
    *,
    finished_at: datetime,
) -> None:
    run = ScrapeRun(
        dealer_id=dealer.id,
        status=STATUS_SUCCESS,
        started_at=finished_at,
        finished_at=finished_at,
    )
    session.add(run)
    session.flush()
    session.add(
        ScrapeLogEntry(
            scrape_run_id=run.id,
            listing_id=listing.id,
            change_type=CHANGE_UPDATED,
            old_price=160_000,
            new_price=150_000,
        )
    )
    session.commit()


def test_status_new_when_never_viewed(session: Session, dealer: Dealer) -> None:
    listing = _add_listing(
        session, dealer, "1", first_seen=_BASE, last_seen=_BASE, last_viewed_at=None
    )

    statuses = listing_statuses(session, [listing])

    assert statuses[listing.id] == STATUS_NEW


def test_status_new_when_first_seen_after_view(session: Session, dealer: Dealer) -> None:
    # Viewed in the past, but the listing was (re)first-seen afterwards.
    listing = _add_listing(
        session,
        dealer,
        "1",
        first_seen=_BASE + timedelta(hours=2),
        last_seen=_BASE + timedelta(hours=2),
        last_viewed_at=_BASE,
    )

    statuses = listing_statuses(session, [listing])

    assert statuses[listing.id] == STATUS_NEW


def test_status_updated_when_price_change_after_view(session: Session, dealer: Dealer) -> None:
    listing = _add_listing(
        session,
        dealer,
        "1",
        first_seen=_BASE - timedelta(days=1),
        last_seen=_BASE + timedelta(hours=2),
        last_viewed_at=_BASE,
    )
    _add_updated_log(session, dealer, listing, finished_at=_BASE + timedelta(hours=2))

    statuses = listing_statuses(session, [listing])

    assert statuses[listing.id] == STATUS_UPDATED


def test_status_seen_when_price_change_before_view(session: Session, dealer: Dealer) -> None:
    listing = _add_listing(
        session,
        dealer,
        "1",
        first_seen=_BASE - timedelta(days=1),
        last_seen=_BASE + timedelta(hours=2),
        last_viewed_at=_BASE,
    )
    # Price change happened before the user last viewed -> already seen.
    _add_updated_log(session, dealer, listing, finished_at=_BASE - timedelta(hours=1))

    statuses = listing_statuses(session, [listing])

    assert statuses[listing.id] == STATUS_SEEN


def test_status_seen_when_viewed_and_no_changes(session: Session, dealer: Dealer) -> None:
    listing = _add_listing(
        session,
        dealer,
        "1",
        first_seen=_BASE - timedelta(days=1),
        last_seen=_BASE,
        last_viewed_at=_BASE + timedelta(hours=1),
    )

    statuses = listing_statuses(session, [listing])

    assert statuses[listing.id] == STATUS_SEEN


def test_new_takes_precedence_over_updated(session: Session, dealer: Dealer) -> None:
    # Never viewed AND has an updated log entry -> still NEW (precedence).
    listing = _add_listing(
        session, dealer, "1", first_seen=_BASE, last_seen=_BASE, last_viewed_at=None
    )
    _add_updated_log(session, dealer, listing, finished_at=_BASE + timedelta(hours=1))

    statuses = listing_statuses(session, [listing])

    assert statuses[listing.id] == STATUS_NEW


def test_unfinished_run_does_not_trigger_updated(session: Session, dealer: Dealer) -> None:
    listing = _add_listing(
        session,
        dealer,
        "1",
        first_seen=_BASE - timedelta(days=1),
        last_seen=_BASE,
        last_viewed_at=_BASE,
    )
    run = ScrapeRun(
        dealer_id=dealer.id,
        status="running",
        started_at=_BASE + timedelta(hours=1),
        finished_at=None,
    )
    session.add(run)
    session.flush()
    session.add(
        ScrapeLogEntry(
            scrape_run_id=run.id,
            listing_id=listing.id,
            change_type=CHANGE_UPDATED,
            old_price=160_000,
            new_price=150_000,
        )
    )
    session.commit()

    statuses = listing_statuses(session, [listing])

    assert statuses[listing.id] == STATUS_SEEN


def test_mark_listing_viewed_records_timestamp(session: Session, dealer: Dealer) -> None:
    listing = _add_listing(
        session, dealer, "1", first_seen=_BASE, last_seen=_BASE, last_viewed_at=None
    )
    assert listing_statuses(session, [listing])[listing.id] == STATUS_NEW

    mark_listing_viewed(session, listing.id)
    session.refresh(listing)

    assert listing.last_viewed_at is not None
    assert listing_statuses(session, [listing])[listing.id] == STATUS_SEEN


def test_mark_listing_viewed_missing_is_noop(session: Session) -> None:
    # Should not raise for a non-existent listing id.
    mark_listing_viewed(session, 999)


def test_listing_statuses_for_mixed_set(session: Session, dealer: Dealer) -> None:
    new = _add_listing(session, dealer, "1", first_seen=_BASE, last_seen=_BASE, last_viewed_at=None)
    updated = _add_listing(
        session,
        dealer,
        "2",
        first_seen=_BASE - timedelta(days=1),
        last_seen=_BASE + timedelta(hours=2),
        last_viewed_at=_BASE,
    )
    _add_updated_log(session, dealer, updated, finished_at=_BASE + timedelta(hours=2))
    seen = _add_listing(
        session,
        dealer,
        "3",
        first_seen=_BASE - timedelta(days=1),
        last_seen=_BASE,
        last_viewed_at=_BASE + timedelta(hours=1),
    )

    listings = list_car_listings(session)
    statuses = listing_statuses(session, listings)

    assert statuses[new.id] == STATUS_NEW
    assert statuses[updated.id] == STATUS_UPDATED
    assert statuses[seen.id] == STATUS_SEEN
