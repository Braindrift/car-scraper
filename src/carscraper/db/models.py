"""ORM models for the core data model.

These classes describe data shape and relationships only — see CLAUDE.md's
"Data Model Summary" for the conceptual model and "Layer responsibilities"
for why no business logic belongs here.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from carscraper.db.session import Base


class Dealer(Base):
    """A car dealer site we scrape listings from."""

    __tablename__ = "dealers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    # Slug identifying the scraper module under scrapers/dealers/, e.g.
    # "bilia_stockholm". Unique so it can be used as a stable reference.
    scraper_module: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Set when a ScrapeRun for this dealer finishes. Nullable until the first
    # run completes.
    last_scraped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    listings: Mapped[list[CarListing]] = relationship(
        back_populates="dealer", cascade="all, delete-orphan"
    )
    scrape_runs: Mapped[list[ScrapeRun]] = relationship(
        back_populates="dealer", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"Dealer(id={self.id!r}, name={self.name!r}, "
            f"scraper_module={self.scraper_module!r})"
        )


class TrackedModel(Base):
    """A make/model (optionally variant/trim) the user wants tracked.

    Configured from the UI; defines what scrapers should look for and what
    listings get surfaced in the dashboard.
    """

    __tablename__ = "tracked_models"
    __table_args__ = (
        UniqueConstraint("make", "model", "variant", name="uq_tracked_models_make_model_variant"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return (
            f"TrackedModel(id={self.id!r}, make={self.make!r}, "
            f"model={self.model!r}, variant={self.variant!r})"
        )


class CarListing(Base):
    """One row per distinct listing per dealer.

    `(dealer_id, external_id)` is the natural key identifying a listing on
    the dealer's site across scrape runs.
    """

    __tablename__ = "car_listings"
    __table_args__ = (
        UniqueConstraint("dealer_id", "external_id", name="uq_car_listings_dealer_external_id"),
        # Supports "avg price per model" / dashboard filtering queries.
        Index("ix_car_listings_make_model", "make", "model"),
        # Supports "currently active listings" queries.
        Index("ix_car_listings_active", "active"),
        # Supports splitting the dashboard's main list from the discarded list.
        Index("ix_car_listings_discarded", "discarded"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dealer_id: Mapped[int] = mapped_column(ForeignKey("dealers.id"), nullable=False)

    # Stable identifier for this listing on the dealer's site (e.g. an id
    # found in the listing URL or page). Used together with dealer_id as the
    # natural key for dedupe/upsert during a scrape run.
    external_id: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(1000), nullable=False)

    make: Mapped[str] = mapped_column(String(100), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    variant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mileage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fuel_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    transmission: Mapped[str | None] = mapped_column(String(50), nullable=True)

    first_seen: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    last_seen: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    # When the user last opened this listing's detail page. Null until first
    # viewed; drives the dashboard NEW/UPDATED status badges (CAR-14).
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # False once a listing isn't seen in a scrape run (implies sold/removed).
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # True when the user has manually set the listing aside ("not interested"
    # or de-cluttering inactive ones). Distinct from `active`: a discarded
    # listing is still scraped/updated and still counts in stats — it's just
    # hidden from the main dashboard list and shown on the Discarded page. The
    # scrape upsert never writes this, so the flag survives re-scrapes.
    discarded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    dealer: Mapped[Dealer] = relationship(back_populates="listings")
    price_snapshots: Mapped[list[PriceSnapshot]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    scrape_log_entries: Mapped[list[ScrapeLogEntry]] = relationship(
        back_populates="listing", cascade="all, delete-orphan"
    )
    images: Mapped[list[ListingImage]] = relationship(
        back_populates="listing",
        cascade="all, delete-orphan",
        order_by="ListingImage.position",
    )

    def __repr__(self) -> str:
        return (
            f"CarListing(id={self.id!r}, dealer_id={self.dealer_id!r}, "
            f"make={self.make!r}, model={self.model!r}, active={self.active!r})"
        )


class ListingImage(Base):
    """One downloaded image for a `CarListing`, used by the detail carousel.

    Images are downloaded to local static storage by `services/images.py`;
    `local_path` is the path *relative to the web static root*
    (`web/static/`), e.g. ``images/<dealer_slug>/<external_id>/0.jpg``, so it
    can be served directly under the app's ``/static`` mount. `position`
    orders the images within a listing's carousel.
    """

    __tablename__ = "listing_images"
    __table_args__ = (
        # A listing's images are addressed by their position; keep them unique
        # so re-downloads don't create duplicate rows for the same slot.
        UniqueConstraint("listing_id", "position", name="uq_listing_images_listing_position"),
        # Supports "all images for this listing, in order" queries.
        Index("ix_listing_images_listing_id_position", "listing_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("car_listings.id"), nullable=False)
    # Path relative to the web static root (web/static/), forward-slashed.
    local_path: Mapped[str] = mapped_column(String(500), nullable=False)
    # Ordering within the listing's carousel; 0-based.
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    listing: Mapped[CarListing] = relationship(back_populates="images")

    def __repr__(self) -> str:
        return (
            f"ListingImage(id={self.id!r}, listing_id={self.listing_id!r}, "
            f"position={self.position!r}, local_path={self.local_path!r})"
        )


class PriceSnapshot(Base):
    """One row appended per scrape run (or per price change) for a listing.

    Drives both per-listing price-history charts and avg-price-per-model
    aggregation queries.
    """

    __tablename__ = "price_snapshots"
    __table_args__ = (
        # Supports "price history for this listing, in order" queries.
        Index("ix_price_snapshots_listing_id_scraped_at", "listing_id", "scraped_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(ForeignKey("car_listings.id"), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    listing: Mapped[CarListing] = relationship(back_populates="price_snapshots")

    def __repr__(self) -> str:
        return (
            f"PriceSnapshot(id={self.id!r}, listing_id={self.listing_id!r}, "
            f"price={self.price!r}, scraped_at={self.scraped_at!r})"
        )


class ScrapeRun(Base):
    """One row per dealer per scrape execution.

    Records the lifecycle (running -> success/failed) and a summary of what
    the run found/changed. Populated by CAR-12's persistence service; this
    model only describes the shape.
    """

    __tablename__ = "scrape_runs"
    __table_args__ = (
        # Supports "latest run(s) for this dealer" queries.
        Index("ix_scrape_runs_dealer_id_started_at", "dealer_id", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dealer_id: Mapped[int] = mapped_column(ForeignKey("dealers.id"), nullable=False)

    # Lifecycle status, e.g. "running" / "success" / "failed".
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    # Null until the run finishes (success or failure).
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Set when status is "failed".
    error_message: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # Summary counts of listing changes observed during the run.
    new_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    removed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unchanged_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    dealer: Mapped[Dealer] = relationship(back_populates="scrape_runs")
    log_entries: Mapped[list[ScrapeLogEntry]] = relationship(
        back_populates="scrape_run", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"ScrapeRun(id={self.id!r}, dealer_id={self.dealer_id!r}, "
            f"status={self.status!r}, started_at={self.started_at!r})"
        )


class ScrapeLogEntry(Base):
    """One row per listing change observed during a ScrapeRun.

    Drives the per-run audit trail (what was new/updated/removed) that CAR-13's
    UI surfaces.
    """

    __tablename__ = "scrape_log_entries"
    __table_args__ = (
        # Supports "all changes for this run" queries.
        Index("ix_scrape_log_entries_scrape_run_id", "scrape_run_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scrape_run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"), nullable=False)
    listing_id: Mapped[int] = mapped_column(ForeignKey("car_listings.id"), nullable=False)

    # The kind of change observed, e.g. "new" / "updated" / "removed".
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Price before/after the change. Both nullable: "new"/"removed" changes may
    # only have one side, and a listing's price itself can be unknown.
    old_price: Mapped[int | None] = mapped_column(Integer, nullable=True)
    new_price: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scrape_run: Mapped[ScrapeRun] = relationship(back_populates="log_entries")
    listing: Mapped[CarListing] = relationship(back_populates="scrape_log_entries")

    def __repr__(self) -> str:
        return (
            f"ScrapeLogEntry(id={self.id!r}, scrape_run_id={self.scrape_run_id!r}, "
            f"listing_id={self.listing_id!r}, change_type={self.change_type!r})"
        )
