"""Tests for `services.scrape_results` (CAR-12).

Exercises the persistence/diff service against a seeded temp SQLite DB,
covering each scenario in the ticket's Definition of Done: new / price-changed
/ unchanged / removed listings, TrackedModel filtering, count + log-entry
accuracy, `Dealer.last_scraped_at` updates, and scraper-error / missing
registration producing a `failed` run instead of an exception.

A configurable test scraper (`_ProgrammableScraper`) is registered under a
dedicated slug so each test can drive the DTOs (or an exception) it returns —
this is the registry's "dummy/test scraper" the ticket points step 3 at.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.config import settings
from carscraper.db.models import (
    CarListing,
    Dealer,
    ListingImage,
    PriceSnapshot,
    ScrapeLogEntry,
    TrackedModel,
)
from carscraper.db.session import Base, create_db_engine
from carscraper.scrapers.base import BaseScraper, CarListingDTO, TrackedModelSpec
from carscraper.scrapers.registry import register
from carscraper.services.scrape_results import (
    CHANGE_NEW,
    CHANGE_REMOVED,
    CHANGE_UPDATED,
    STATUS_FAILED,
    STATUS_SUCCESS,
    filter_tracked,
    scrape_and_persist_dealer,
)

# DTOs / behaviour the programmable scraper returns. Mutated per-test before
# calling the service; the scraper instance reads these module-level slots.
_NEXT_DTOS: list[CarListingDTO] = []
_RAISE: Exception | None = None

_SLUG = "test_programmable"


@register(_SLUG)
class _ProgrammableScraper(BaseScraper):
    """Returns `_NEXT_DTOS`, or raises `_RAISE` if set, for the current test."""

    async def scrape(self, tracked: list[TrackedModelSpec] | None = None) -> list[CarListingDTO]:
        if _RAISE is not None:
            raise _RAISE
        return list(_NEXT_DTOS)


def _set_scrape(dtos: list[CarListingDTO] | None = None, raises: Exception | None = None) -> None:
    global _NEXT_DTOS, _RAISE
    _NEXT_DTOS = dtos or []
    _RAISE = raises


@pytest.fixture(autouse=True)
def _reset_scraper() -> Generator[None, None, None]:
    _set_scrape([])
    yield
    _set_scrape([])


@pytest.fixture
def session(tmp_path) -> Generator[Session, None, None]:
    db_path = tmp_path / "scrape_results_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _make_dealer(session: Session, slug: str = _SLUG) -> Dealer:
    dealer = Dealer(name="Test Dealer", base_url="https://example.com", scraper_module=slug)
    session.add(dealer)
    session.commit()
    return dealer


def _track(session: Session, make: str, model: str, variant: str | None = None) -> None:
    session.add(TrackedModel(make=make, model=model, variant=variant))
    session.commit()


def _dto(
    external_id: str,
    *,
    price: int | None,
    make="Volvo",
    model="V70",
    variant=None,
    image_urls: list[str] | None = None,
):
    return CarListingDTO(
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        make=make,
        model=model,
        variant=variant,
        price=price,
        image_urls=image_urls or [],
    )


def _log_entries(session: Session, run_id: int) -> list[ScrapeLogEntry]:
    stmt = select(ScrapeLogEntry).where(ScrapeLogEntry.scrape_run_id == run_id)
    return list(session.execute(stmt).scalars())


# --- filter_tracked ---------------------------------------------------------


def test_filter_tracked_empty_tracked_keeps_nothing() -> None:
    dtos = [_dto("a", price=1)]
    assert filter_tracked(dtos, []) == []


def test_filter_tracked_make_model_match_case_insensitive() -> None:
    tracked = [TrackedModel(make="volvo", model="v70", variant=None)]
    dtos = [_dto("a", price=1, make="Volvo", model="V70")]
    assert filter_tracked(dtos, tracked) == dtos


def test_filter_tracked_variant_pinned_requires_variant_match() -> None:
    tracked = [TrackedModel(make="Volvo", model="V70", variant="T5")]
    match = _dto("a", price=1, variant="T5")
    no_variant = _dto("b", price=1, variant=None)
    other_variant = _dto("c", price=1, variant="D4")
    assert filter_tracked([match, no_variant, other_variant], tracked) == [match]


def test_filter_tracked_no_variant_matches_any_variant() -> None:
    tracked = [TrackedModel(make="Volvo", model="V70", variant=None)]
    a = _dto("a", price=1, variant="T5")
    b = _dto("b", price=1, variant=None)
    assert filter_tracked([a, b], tracked) == [a, b]


def test_filter_tracked_excludes_untracked_make_model() -> None:
    tracked = [TrackedModel(make="Volvo", model="V70", variant=None)]
    dtos = [_dto("a", price=1, make="Toyota", model="Corolla")]
    assert filter_tracked(dtos, tracked) == []


# --- new / unchanged / price-changed / removed ------------------------------


async def test_new_listing_persists_listing_snapshot_and_log(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")
    _set_scrape([_dto("v70-1", price=189000)])

    run = await scrape_and_persist_dealer(session, dealer)

    assert run.status == STATUS_SUCCESS
    assert (run.new_count, run.updated_count, run.removed_count, run.unchanged_count) == (
        1,
        0,
        0,
        0,
    )
    listing = session.execute(select(CarListing)).scalar_one()
    assert listing.external_id == "v70-1"
    assert listing.price == 189000
    assert listing.active is True
    assert listing.first_seen == listing.last_seen

    snapshots = session.execute(select(PriceSnapshot)).scalars().all()
    assert [s.price for s in snapshots] == [189000]

    entries = _log_entries(session, run.id)
    assert len(entries) == 1
    assert entries[0].change_type == CHANGE_NEW
    assert entries[0].old_price is None
    assert entries[0].new_price == 189000

    assert dealer.last_scraped_at == run.finished_at


async def test_price_unchanged_bumps_last_seen_only(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")

    _set_scrape([_dto("v70-1", price=189000)])
    first = await scrape_and_persist_dealer(session, dealer)
    listing = session.execute(select(CarListing)).scalar_one()
    first_seen = listing.first_seen

    _set_scrape([_dto("v70-1", price=189000)])
    second = await scrape_and_persist_dealer(session, dealer)

    session.refresh(listing)
    assert second.unchanged_count == 1
    assert second.new_count == 0 and second.updated_count == 0
    assert listing.first_seen == first_seen
    assert listing.last_seen >= first_seen
    # No second snapshot, no extra log entry.
    assert session.execute(select(PriceSnapshot)).scalars().all().__len__() == 1
    assert _log_entries(session, second.id) == []
    assert first.id != second.id


async def test_price_changed_appends_snapshot_and_updated_log(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")

    _set_scrape([_dto("v70-1", price=189000)])
    await scrape_and_persist_dealer(session, dealer)

    _set_scrape([_dto("v70-1", price=179000)])
    run = await scrape_and_persist_dealer(session, dealer)

    listing = session.execute(select(CarListing)).scalar_one()
    assert listing.price == 179000
    assert run.updated_count == 1
    snapshots = session.execute(select(PriceSnapshot).order_by(PriceSnapshot.id)).scalars().all()
    assert [s.price for s in snapshots] == [189000, 179000]

    entries = _log_entries(session, run.id)
    assert len(entries) == 1
    assert entries[0].change_type == CHANGE_UPDATED
    assert entries[0].old_price == 189000
    assert entries[0].new_price == 179000


async def test_unseen_active_listing_marked_removed(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")

    _set_scrape([_dto("v70-1", price=189000), _dto("v70-2", price=200000)])
    await scrape_and_persist_dealer(session, dealer)

    # Second run: v70-2 is gone.
    _set_scrape([_dto("v70-1", price=189000)])
    run = await scrape_and_persist_dealer(session, dealer)

    assert run.removed_count == 1
    assert run.unchanged_count == 1
    gone = session.execute(select(CarListing).where(CarListing.external_id == "v70-2")).scalar_one()
    assert gone.active is False

    entries = _log_entries(session, run.id)
    assert len(entries) == 1
    assert entries[0].change_type == CHANGE_REMOVED
    assert entries[0].listing_id == gone.id
    assert entries[0].old_price == 200000
    assert entries[0].new_price is None


async def test_already_inactive_listing_not_relogged_as_removed(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")

    _set_scrape([_dto("v70-1", price=189000), _dto("v70-2", price=200000)])
    await scrape_and_persist_dealer(session, dealer)
    _set_scrape([_dto("v70-1", price=189000)])  # v70-2 removed
    await scrape_and_persist_dealer(session, dealer)
    _set_scrape([_dto("v70-1", price=189000)])  # v70-2 still gone
    run = await scrape_and_persist_dealer(session, dealer)

    assert run.removed_count == 0
    assert _log_entries(session, run.id) == []


async def test_reappearing_listing_is_reactivated(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")

    _set_scrape([_dto("v70-1", price=189000)])
    await scrape_and_persist_dealer(session, dealer)
    _set_scrape([])  # removed
    await scrape_and_persist_dealer(session, dealer)
    _set_scrape([_dto("v70-1", price=189000)])  # back, same price
    run = await scrape_and_persist_dealer(session, dealer)

    listing = session.execute(select(CarListing)).scalar_one()
    assert listing.active is True
    # Same price as before -> counted unchanged, reactivated.
    assert run.unchanged_count == 1


# --- TrackedModel filtering during persist ----------------------------------


async def test_only_tracked_models_persisted(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")
    _set_scrape(
        [
            _dto("v70-1", price=189000, make="Volvo", model="V70"),
            _dto("corolla-1", price=120000, make="Toyota", model="Corolla"),
        ]
    )

    run = await scrape_and_persist_dealer(session, dealer)

    listings = session.execute(select(CarListing)).scalars().all()
    assert {listing.external_id for listing in listings} == {"v70-1"}
    assert run.new_count == 1


async def test_no_tracked_models_persists_nothing(session: Session) -> None:
    dealer = _make_dealer(session)
    _set_scrape([_dto("v70-1", price=189000)])

    run = await scrape_and_persist_dealer(session, dealer)

    assert session.execute(select(CarListing)).scalars().all() == []
    assert (run.new_count, run.updated_count, run.removed_count, run.unchanged_count) == (
        0,
        0,
        0,
        0,
    )
    assert run.status == STATUS_SUCCESS


# --- listing with unknown price ---------------------------------------------


async def test_new_listing_without_price_skips_snapshot(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")
    _set_scrape([_dto("v70-1", price=None)])

    run = await scrape_and_persist_dealer(session, dealer)

    assert run.new_count == 1
    assert session.execute(select(PriceSnapshot)).scalars().all() == []
    entries = _log_entries(session, run.id)
    assert entries[0].change_type == CHANGE_NEW
    assert entries[0].new_price is None


# --- error handling ---------------------------------------------------------


async def test_scraper_exception_results_in_failed_run(session: Session) -> None:
    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")
    _set_scrape(raises=RuntimeError("dealer site down"))

    run = await scrape_and_persist_dealer(session, dealer)

    assert run.status == STATUS_FAILED
    assert run.finished_at is not None
    assert "dealer site down" in (run.error_message or "")
    assert session.execute(select(CarListing)).scalars().all() == []
    # last_scraped_at not advanced on failure.
    assert dealer.last_scraped_at is None


async def test_missing_scraper_registration_results_in_failed_run(session: Session) -> None:
    dealer = _make_dealer(session, slug="not_registered_slug")
    _track(session, "Volvo", "V70")

    run = await scrape_and_persist_dealer(session, dealer)

    assert run.status == STATUS_FAILED
    assert run.error_message is not None
    assert dealer.last_scraped_at is None


# --- image download wiring (CAR-15) -----------------------------------------


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Records requests; constructed by `download_listing_images` (no network)."""

    requested: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def get(self, url: str) -> _FakeResponse:
        _FakeClient.requested.append(url)
        return _FakeResponse(b"fake-image-bytes")

    def close(self) -> None:
        return None


async def test_persist_downloads_dto_images(session, tmp_path, monkeypatch) -> None:
    # Route downloads to a temp static root and stub out the HTTP client so no
    # real network call happens.
    monkeypatch.setattr(settings, "static_root", tmp_path / "static")
    monkeypatch.setattr("carscraper.services.images.httpx.Client", _FakeClient)
    _FakeClient.requested = []

    dealer = _make_dealer(session)
    _track(session, "Volvo", "V70")
    urls = ["https://img.example/a.jpg", "https://img.example/b.jpg"]
    _set_scrape([_dto("v70-1", price=189000, image_urls=urls)])

    await scrape_and_persist_dealer(session, dealer)

    listing = session.execute(select(CarListing)).scalar_one()
    images = (
        session.execute(
            select(ListingImage)
            .where(ListingImage.listing_id == listing.id)
            .order_by(ListingImage.position)
        )
        .scalars()
        .all()
    )
    assert [img.position for img in images] == [0, 1]
    assert _FakeClient.requested == urls
    # The files were written under the temp static root.
    for img in images:
        assert (settings.static_root / img.local_path).is_file()

    # Re-running with the same images doesn't re-download (idempotent wiring).
    _FakeClient.requested = []
    _set_scrape([_dto("v70-1", price=189000, image_urls=urls)])
    await scrape_and_persist_dealer(session, dealer)
    assert _FakeClient.requested == []
    assert session.execute(select(ListingImage)).scalars().all().__len__() == 2
