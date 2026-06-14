"""Read-side queries + background launching for the scrape UI (CAR-13).

The web layer (`web/routes.py`) needs three things the persist/diff service
(`services/scrape_results.py`, CAR-12) deliberately doesn't provide, because
they're about *driving and observing* scrapes rather than performing one:

- Listing dealers alongside the status of their most recent `ScrapeRun`, to
  render the `/scrape` page and its HTMX-polled status rows.
- Fetching a finished run's `ScrapeLogEntry` list (with the related listing) to
  render its report.
- Launching a dealer scrape in the background so the HTTP request can return
  immediately while the run progresses.

This stays in `services/` (not `web/`) per CLAUDE.md: routers never construct
ORM queries directly, and "trigger scrapes for all enabled dealers" is exactly
the kind of cross-cutting orchestration that belongs in a service. The web
layer only calls these and renders the results.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from carscraper.db.models import Dealer, ScrapeLogEntry, ScrapeRun
from carscraper.db.session import get_session
from carscraper.services.scrape_results import scrape_and_persist_dealer


@dataclass(frozen=True)
class DealerScrapeStatus:
    """A dealer plus its most recent `ScrapeRun` (if any), for the UI rows."""

    dealer: Dealer
    latest_run: ScrapeRun | None


def latest_run_for_dealer(session: Session, dealer_id: int) -> ScrapeRun | None:
    """Return the most recent `ScrapeRun` for a dealer, or `None` if it never ran."""
    stmt = (
        select(ScrapeRun)
        .where(ScrapeRun.dealer_id == dealer_id)
        .order_by(ScrapeRun.started_at.desc(), ScrapeRun.id.desc())
        .limit(1)
    )
    return session.execute(stmt).scalars().first()


def list_dealer_scrape_status(session: Session) -> list[DealerScrapeStatus]:
    """Return every dealer with its latest run, ordered by dealer name.

    Drives the `/scrape` page and its HTMX status partial. Dealers that have
    never been scraped get `latest_run=None` (rendered as "never").
    """
    dealers = session.execute(select(Dealer).order_by(Dealer.name)).scalars().all()
    return [
        DealerScrapeStatus(dealer=dealer, latest_run=latest_run_for_dealer(session, dealer.id))
        for dealer in dealers
    ]


def get_scrape_run(session: Session, run_id: int) -> ScrapeRun | None:
    """Return a single `ScrapeRun` by id (with its dealer), or `None`.

    The `dealer` relationship is eager-loaded so the report template can show
    the dealer name after the request's session has closed.
    """
    stmt = select(ScrapeRun).where(ScrapeRun.id == run_id).options(joinedload(ScrapeRun.dealer))
    return session.execute(stmt).scalars().first()


def get_run_log_entries(session: Session, run_id: int) -> list[ScrapeLogEntry]:
    """Return a run's `ScrapeLogEntry` rows (with their listing) for the report.

    Ordered by entry id (i.e. the order changes were recorded during the run).
    The related `CarListing` is eager-loaded so the template can show per-listing
    details without triggering lazy loads after the session closes.
    """
    stmt = (
        select(ScrapeLogEntry)
        .where(ScrapeLogEntry.scrape_run_id == run_id)
        .options(joinedload(ScrapeLogEntry.listing))
        .order_by(ScrapeLogEntry.id)
    )
    return list(session.execute(stmt).scalars())


async def scrape_dealer_by_id(dealer_id: int) -> None:
    """Run + persist one dealer's scrape in a fresh session.

    Used as the background task body: it opens its own `get_session()` because
    the request-scoped session that triggered it is already closed by the time
    this runs. A missing dealer id is a no-op (the row may have been deleted
    between the trigger and the task running).
    """
    with get_session() as session:
        dealer = session.get(Dealer, dealer_id)
        if dealer is None:
            return
        await scrape_and_persist_dealer(session, dealer)


async def scrape_all_enabled_dealers() -> None:
    """Run + persist a scrape for every enabled dealer, sequentially.

    Each dealer is scraped in turn; `scrape_and_persist_dealer` records a
    `failed` run rather than raising, so one failing dealer doesn't abort the
    rest.
    """
    with get_session() as session:
        dealers = (
            session.execute(select(Dealer).where(Dealer.enabled.is_(True)).order_by(Dealer.name))
            .scalars()
            .all()
        )
        for dealer in dealers:
            await scrape_and_persist_dealer(session, dealer)


def launch_dealer_scrape(dealer_id: int) -> None:
    """Schedule a background scrape of one dealer on the running event loop."""
    asyncio.create_task(scrape_dealer_by_id(dealer_id))


def launch_all_dealers_scrape() -> None:
    """Schedule a background scrape of all enabled dealers on the running loop."""
    asyncio.create_task(scrape_all_enabled_dealers())
