"""Persist + diff a dealer's scraped listings (CAR-12).

This is the business-logic half of a scrape that `services/scrape_runner.py`
(CAR-4) explicitly deferred: turning a dealer's `CarListingDTO`s into
persisted, deduplicated `CarListing`/`PriceSnapshot` rows while recording what
changed via CAR-11's `ScrapeRun`/`ScrapeLogEntry` models.

Responsibilities (per CLAUDE.md "services mediate"): this is the *only* layer
that talks to both the scraper registry and the DB for a scrape. It is kept
separate from `scrape_runner` so each module stays focused on one job —
`scrape_runner` fetches DTOs, `scrape_results` persists/diffs them.

The flow for one dealer (`scrape_and_persist_dealer`):

1. Open a `ScrapeRun` (`status="running"`).
2. Run the dealer's scraper to get `CarListingDTO`s.
3. Keep only DTOs matching a configured `TrackedModel` (make + model, plus
   variant if the `TrackedModel` pins one).
4. Upsert each kept DTO by `(dealer_id, external_id)`:
   - new listing -> create row + initial `PriceSnapshot` + "new" log entry;
   - existing + price changed -> update price/`last_seen`, append a
     `PriceSnapshot`, "updated" log entry;
   - existing + price unchanged -> bump `last_seen` only, counted "unchanged".
5. Mark previously-active listings not seen this run `active=False` with a
   "removed" log entry.
6. Finalize the run (`success`, counts, `Dealer.last_scraped_at`).
7. On scraper error / missing registration, finalize the run `failed` with an
   `error_message` instead of letting the exception propagate — so a
   "scrape all dealers" loop can keep going.

Change-type / status string constants live here (not on the models) because
they're a service-level concept; the models only store the strings.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.db.models import (
    CarListing,
    Dealer,
    PriceSnapshot,
    ScrapeLogEntry,
    ScrapeRun,
    TrackedModel,
)
from carscraper.scrapers.base import CarListingDTO, TrackedModelSpec
from carscraper.scrapers.registry import run_scraper
from carscraper.services.images import download_listing_images

# ScrapeRun.status values.
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

# ScrapeLogEntry.change_type values.
CHANGE_NEW = "new"
CHANGE_UPDATED = "updated"
CHANGE_REMOVED = "removed"


def _now() -> datetime:
    """Naive UTC timestamp, matching the models' `func.now()` columns.

    The `DateTime` columns are timezone-naive and their `func.now()`
    server defaults resolve to naive UTC on SQLite, so service-set
    timestamps use the same convention (see `services/demo_data.py`).
    """
    return datetime.now(UTC).replace(tzinfo=None)


def _matches_tracked(dto: CarListingDTO, tracked: list[TrackedModel]) -> bool:
    """Return whether `dto` matches any `TrackedModel`.

    A `TrackedModel` matches on make + model (case-insensitive). If the
    `TrackedModel` pins a `variant`, the DTO's variant must match it too
    (also case-insensitive); a `TrackedModel` with no variant matches the
    make/model regardless of the DTO's variant.
    """
    dto_make = dto.make.casefold()
    dto_model = dto.model.casefold()
    dto_variant = dto.variant.casefold() if dto.variant is not None else None

    for tm in tracked:
        if tm.make.casefold() != dto_make or tm.model.casefold() != dto_model:
            continue
        if tm.variant is None:
            return True
        if dto_variant is not None and tm.variant.casefold() == dto_variant:
            return True
    return False


def filter_tracked(dtos: list[CarListingDTO], tracked: list[TrackedModel]) -> list[CarListingDTO]:
    """Keep only the DTOs matching at least one `TrackedModel`.

    With no tracked models configured, nothing is tracked, so an empty list
    is returned (the user hasn't asked for anything to be persisted yet).
    """
    if not tracked:
        return []
    return [dto for dto in dtos if _matches_tracked(dto, tracked)]


def _existing_listings_by_external_id(session: Session, dealer_id: int) -> dict[str, CarListing]:
    """Map every existing `CarListing.external_id` for a dealer to its row."""
    stmt = select(CarListing).where(CarListing.dealer_id == dealer_id)
    return {listing.external_id: listing for listing in session.execute(stmt).scalars()}


def _apply_dto_specs(listing: CarListing, dto: CarListingDTO) -> None:
    """Copy the DTO's spec fields onto an existing listing.

    Price and `last_seen` are handled by the caller (they drive the
    new/updated/unchanged decision); everything else is refreshed in case the
    dealer corrected/changed a listing's details between runs.
    """
    listing.url = dto.url
    listing.make = dto.make
    listing.model = dto.model
    listing.variant = dto.variant
    listing.year = dto.year
    listing.mileage = dto.mileage
    listing.fuel_type = dto.fuel_type
    listing.transmission = dto.transmission


def persist_scrape_results(
    session: Session,
    dealer: Dealer,
    scrape_run: ScrapeRun,
    dtos: list[CarListingDTO],
    tracked: list[TrackedModel],
    now: datetime,
) -> None:
    """Diff `dtos` against the dealer's stored listings and persist changes.

    Updates `scrape_run`'s counts and appends `ScrapeLogEntry` rows in place.
    Assumes `scrape_run` is already persisted (has an id). Does not commit —
    the caller (`scrape_and_persist_dealer`) owns transaction boundaries.
    """
    kept = filter_tracked(dtos, tracked)
    existing = _existing_listings_by_external_id(session, dealer.id)
    seen_external_ids: set[str] = set()

    new_count = 0
    updated_count = 0
    unchanged_count = 0

    for dto in kept:
        seen_external_ids.add(dto.external_id)
        listing = existing.get(dto.external_id)

        if listing is None:
            listing = CarListing(
                dealer=dealer,
                external_id=dto.external_id,
                url=dto.url,
                make=dto.make,
                model=dto.model,
                variant=dto.variant,
                year=dto.year,
                mileage=dto.mileage,
                price=dto.price,
                fuel_type=dto.fuel_type,
                transmission=dto.transmission,
                first_seen=now,
                last_seen=now,
                active=True,
            )
            session.add(listing)
            session.flush()  # assign listing.id for the snapshot/log FKs
            new_count += 1
            if dto.price is not None:
                session.add(PriceSnapshot(listing_id=listing.id, price=dto.price, scraped_at=now))
            session.add(
                ScrapeLogEntry(
                    scrape_run_id=scrape_run.id,
                    listing_id=listing.id,
                    change_type=CHANGE_NEW,
                    old_price=None,
                    new_price=dto.price,
                )
            )
            # Download any images the DTO carries (idempotent — no-op if none).
            download_listing_images(session, listing, dto.image_urls)
            continue

        old_price = listing.price
        _apply_dto_specs(listing, dto)
        listing.last_seen = now
        # A listing that had gone inactive but is seen again is reactivated.
        listing.active = True
        # Pull in any newly-published images (idempotent for already-stored ones).
        download_listing_images(session, listing, dto.image_urls)

        if dto.price != old_price:
            listing.price = dto.price
            updated_count += 1
            if dto.price is not None:
                session.add(PriceSnapshot(listing_id=listing.id, price=dto.price, scraped_at=now))
            session.add(
                ScrapeLogEntry(
                    scrape_run_id=scrape_run.id,
                    listing_id=listing.id,
                    change_type=CHANGE_UPDATED,
                    old_price=old_price,
                    new_price=dto.price,
                )
            )
        else:
            unchanged_count += 1

    # Listings that were active but weren't seen this run are now removed/sold.
    removed_count = 0
    for external_id, listing in existing.items():
        if external_id in seen_external_ids:
            continue
        if not listing.active:
            continue
        listing.active = False
        removed_count += 1
        session.add(
            ScrapeLogEntry(
                scrape_run_id=scrape_run.id,
                listing_id=listing.id,
                change_type=CHANGE_REMOVED,
                old_price=listing.price,
                new_price=None,
            )
        )

    scrape_run.new_count = new_count
    scrape_run.updated_count = updated_count
    scrape_run.removed_count = removed_count
    scrape_run.unchanged_count = unchanged_count


async def scrape_and_persist_dealer(session: Session, dealer: Dealer) -> ScrapeRun:
    """Run + persist one dealer's scrape, returning its finalized `ScrapeRun`.

    Opens a `ScrapeRun` (`status="running"`), runs the dealer's scraper,
    filters to tracked models, diffs/persists the results, and finalizes the
    run. If the scraper raises or its `scraper_module` slug isn't registered,
    the run is finalized `status="failed"` with an `error_message` rather than
    propagating the exception — so a "scrape all dealers" loop can continue
    with the remaining dealers.
    """
    started_at = _now()
    scrape_run = ScrapeRun(
        dealer_id=dealer.id,
        status=STATUS_RUNNING,
        started_at=started_at,
    )
    session.add(scrape_run)
    session.commit()  # persist the "running" run so it's visible even on crash

    try:
        tracked = list(session.execute(select(TrackedModel)).scalars())
        tracked_specs = [
            TrackedModelSpec(make=tm.make, model=tm.model, variant=tm.variant) for tm in tracked
        ]
        dtos = await run_scraper(dealer.scraper_module, tracked_specs)
        finished_at = _now()
        persist_scrape_results(session, dealer, scrape_run, dtos, tracked, finished_at)

        scrape_run.status = STATUS_SUCCESS
        scrape_run.finished_at = finished_at
        dealer.last_scraped_at = finished_at
        session.commit()
    except Exception as exc:  # noqa: BLE001 - failure is recorded, not swallowed silently
        session.rollback()
        # Re-fetch the run in the rolled-back session and mark it failed.
        scrape_run = session.get(ScrapeRun, scrape_run.id)
        scrape_run.status = STATUS_FAILED
        scrape_run.finished_at = _now()
        scrape_run.error_message = f"{type(exc).__name__}: {exc}"[:2000]
        session.commit()

    return scrape_run
