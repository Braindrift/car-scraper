"""CRUD operations for `Dealer` rows.

Per CLAUDE.md, routers/web/CLI never construct SQL/ORM queries directly —
they call into this module. This currently only provides the minimal
operations needed by `services.demo_data` (CAR-9); dealer management UI is
out of scope for now.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.db.models import Dealer


def list_dealers(session: Session) -> list[Dealer]:
    """Return all `Dealer` rows, ordered by name."""
    stmt = select(Dealer).order_by(Dealer.name)
    return list(session.execute(stmt).scalars().all())


def get_dealer_by_scraper_module(session: Session, scraper_module: str) -> Dealer | None:
    """Return the `Dealer` row with the given `scraper_module` slug, if any."""
    stmt = select(Dealer).where(Dealer.scraper_module == scraper_module)
    return session.execute(stmt).scalar_one_or_none()


def create_dealer(
    session: Session,
    name: str,
    base_url: str,
    scraper_module: str,
    enabled: bool = True,
) -> Dealer:
    """Create and persist a new `Dealer` row.

    `scraper_module` must be unique (it's the slug used to resolve a
    `BaseScraper` via `scrapers.registry`); callers are responsible for
    avoiding duplicates.
    """
    dealer = Dealer(name=name, base_url=base_url, scraper_module=scraper_module, enabled=enabled)
    session.add(dealer)
    session.commit()
    return dealer


def delete_dealer(session: Session, dealer_id: int) -> bool:
    """Delete the `Dealer` row with the given id (and its listings, via cascade).

    Returns `True` if a row was deleted, `False` if no row with that id
    existed.
    """
    dealer = session.get(Dealer, dealer_id)
    if dealer is None:
        return False

    session.delete(dealer)
    session.commit()
    return True
