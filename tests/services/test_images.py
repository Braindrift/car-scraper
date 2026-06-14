"""Tests for `services.images` (CAR-15).

Covers, with **no real network calls** (a fake HTTP client is injected):

- downloading image URLs writes files under the configured static root and
  creates `ListingImage` rows with the expected relative `local_path`s;
- a `ListingImage` round-trips (the rows persist and re-read in order);
- idempotency — re-running for the same listing does not re-fetch or create
  duplicate rows, and a partial download only fills the missing positions;
- the empty-`image_urls` case is a no-op.

`settings.static_root` is monkeypatched to a temp dir so nothing is written
into the package's static tree.
"""

from __future__ import annotations

from collections.abc import Generator

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from carscraper.config import settings
from carscraper.db.models import CarListing, Dealer, ListingImage
from carscraper.db.session import Base, create_db_engine
from carscraper.services.images import download_listing_images


@pytest.fixture
def session(tmp_path, monkeypatch) -> Generator[Session, None, None]:
    db_path = tmp_path / "images_test.db"
    engine = create_db_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Redirect downloads into a temp static root, never the package.
    monkeypatch.setattr(settings, "static_root", tmp_path / "static")

    with Session(engine) as session:
        yield session

    engine.dispose()


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    """Minimal stand-in for httpx.Client that records requested URLs."""

    def __init__(self, contents: dict[str, bytes]) -> None:
        self._contents = contents
        self.requested: list[str] = []

    def get(self, url: str) -> _FakeResponse:
        self.requested.append(url)
        return _FakeResponse(self._contents[url])

    def close(self) -> None:  # pragma: no cover - injected clients aren't closed
        raise AssertionError("download_listing_images must not close injected clients")


def _make_listing(session: Session, *, slug: str = "demo_bilia") -> CarListing:
    dealer = Dealer(name="Demo", base_url="https://demo.example", scraper_module=slug)
    session.add(dealer)
    session.commit()

    listing = CarListing(
        dealer=dealer,
        external_id="abc-123",
        url="https://demo.example/abc-123",
        make="Volvo",
        model="V70",
    )
    session.add(listing)
    session.commit()
    return listing


def test_download_writes_files_and_rows(session: Session) -> None:
    listing = _make_listing(session)
    urls = ["https://img.example/a.jpg", "https://img.example/b.png"]
    client = _FakeClient({urls[0]: b"AAA", urls[1]: b"BBB"})

    created = download_listing_images(session, listing, urls, client=client)
    session.commit()

    assert len(created) == 2
    assert client.requested == urls

    # Files exist on disk under the configured static root, named by position.
    static_root = settings.static_root
    file0 = static_root / "images" / "demo_bilia" / "abc-123" / "0.jpg"
    file1 = static_root / "images" / "demo_bilia" / "abc-123" / "1.png"
    assert file0.read_bytes() == b"AAA"
    assert file1.read_bytes() == b"BBB"

    # Rows store the static-root-relative, forward-slashed path.
    rows = (
        session.execute(
            select(ListingImage)
            .where(ListingImage.listing_id == listing.id)
            .order_by(ListingImage.position)
        )
        .scalars()
        .all()
    )
    assert [r.local_path for r in rows] == [
        "images/demo_bilia/abc-123/0.jpg",
        "images/demo_bilia/abc-123/1.png",
    ]
    assert [r.position for r in rows] == [0, 1]


def test_listing_image_round_trip(session: Session) -> None:
    listing = _make_listing(session)
    urls = ["https://img.example/a.jpg"]
    download_listing_images(session, listing, urls, client=_FakeClient({urls[0]: b"X"}))
    session.commit()

    fetched = session.get(CarListing, listing.id)
    assert len(fetched.images) == 1
    image = fetched.images[0]
    assert image.position == 0
    assert image.local_path == "images/demo_bilia/abc-123/0.jpg"
    assert image.listing_id == listing.id


def test_download_is_idempotent(session: Session) -> None:
    listing = _make_listing(session)
    urls = ["https://img.example/a.jpg", "https://img.example/b.jpg"]
    contents = {urls[0]: b"AAA", urls[1]: b"BBB"}

    download_listing_images(session, listing, urls, client=_FakeClient(contents))
    session.commit()

    # Second run: every position already exists -> no HTTP, no new rows.
    second_client = _FakeClient(contents)
    created = download_listing_images(session, listing, urls, client=second_client)
    session.commit()

    assert created == []
    assert second_client.requested == []
    rows = (
        session.execute(select(ListingImage).where(ListingImage.listing_id == listing.id))
        .scalars()
        .all()
    )
    assert len(rows) == 2


def test_download_fills_only_missing_positions(session: Session) -> None:
    listing = _make_listing(session)
    urls = ["https://img.example/a.jpg", "https://img.example/b.jpg"]
    contents = {urls[0]: b"AAA", urls[1]: b"BBB"}

    # Simulate a partial first run that only got position 0.
    download_listing_images(session, listing, urls[:1], client=_FakeClient(contents))
    session.commit()

    # Re-run with the full list: only the missing position (1) is fetched.
    client = _FakeClient(contents)
    created = download_listing_images(session, listing, urls, client=client)
    session.commit()

    assert len(created) == 1
    assert created[0].position == 1
    assert client.requested == [urls[1]]


def test_download_no_urls_is_noop(session: Session) -> None:
    listing = _make_listing(session)
    created = download_listing_images(session, listing, [], client=_FakeClient({}))
    session.commit()

    assert created == []
    rows = (
        session.execute(select(ListingImage).where(ListingImage.listing_id == listing.id))
        .scalars()
        .all()
    )
    assert rows == []
