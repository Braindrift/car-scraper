# CarScraper 2.0

## Project Overview

CarScraper 2.0 is a personal tool for tracking used-car listings from a curated set of
Swedish car dealer websites (initially 5-10 dealers). It runs as a daily batch job
(no live/real-time updates needed) and presents results through a local web dashboard.

Core capabilities:
- Scrape listings from each configured dealer site for a configurable set of
  tracked makes/models (configured from the UI).
- Normalize and store listings, tracking when a listing first/last appeared and
  whether it's still active (i.e. not sold/removed).
- Track price history per listing over time.
- Surface meta-information: average price per model, price development for a
  specific listing, etc.

This is a single-user, locally-run application. There is no need for
multi-tenant auth, horizontal scaling, or a hosted database.

## Tech Stack

- **Language/runtime**: Python 3.12
- **API/backend**: FastAPI — async-friendly, plays well with Playwright, gives us
  a typed API layer for free via Pydantic.
- **Database**: SQLite, accessed through SQLAlchemy 2.0 ORM, with Alembic for
  migrations. SQLite is file-based and zero-config, which fits a single-user
  local app perfectly (trivial to back up — just copy the file). Going through
  SQLAlchemy means a future move to Postgres, if ever needed, is a config
  change rather than a rewrite.
- **Validation/schemas**: Pydantic (shared with FastAPI request/response models).
- **Scraping**: Playwright (for JS-heavy dealer sites that render listings
  client-side) + BeautifulSoup (HTML parsing) + httpx (for simple static pages
  that don't need a browser). Each dealer gets its own scraper module behind a
  shared `BaseScraper` interface — see "Design Discipline" below. We deliberately
  do **not** use Scrapy: Scrapy's own async/event-loop model adds friction when
  mixed with Playwright's async API, and at this scale (5-10 dealers, daily
  batch) its extra machinery (pipelines, middlewares, built-in scheduler) isn't
  worth the learning curve.
- **Frontend**: Server-rendered Jinja2 templates + HTMX (for partial-page
  updates — filtering, sorting, etc. without full reloads) + Tailwind CSS for
  styling. Keeping the frontend in the same Python codebase avoids a second
  build pipeline/deployment story for what is a small local dashboard.
- **Charts**: Chart.js, embedded in Jinja2 pages, for price-history/trend
  visuals.
- **CLI**: Typer — for running scrapes manually or from a scheduled task
  (`run-scrape`, `run-scrape --dealer=<name>`).
- **Scheduling**: Windows Task Scheduler invokes a script (see `scripts/`) to
  run the daily scrape. No in-app scheduler needed.
- **Lint/format/types**: ruff (lint) + black (format), mypy optional but
  encouraged for `scrapers/`, `services/`, and `db/`.
- **Testing**: pytest. Scrapers are tested against **saved HTML fixtures**, not
  live sites — this keeps tests fast/deterministic and lets us detect when a
  dealer changes their site layout (the fixture stops matching reality, the
  scraper needs updating).

## Architecture & Project Structure

```
car-scraper/
├── CLAUDE.md
├── pyproject.toml
├── alembic/                   # DB migrations
├── src/carscraper/
│   ├── main.py                # FastAPI app entrypoint
│   ├── config.py              # pydantic-settings (paths, dealer config, etc.)
│   ├── db/                    # SQLAlchemy models + session management
│   ├── schemas/               # Pydantic schemas for API I/O
│   ├── scrapers/
│   │   ├── base.py            # BaseScraper ABC + CarListingDTO
│   │   ├── registry.py        # discovers/runs enabled scrapers
│   │   └── dealers/           # one module per dealer site
│   ├── services/               # business logic: normalization, dedupe,
│   │                            # price-history tracking, stats/aggregation
│   ├── api/                    # FastAPI routers (listings, dealers, config, stats)
│   ├── web/                     # Jinja2 templates + static assets
│   │                             # (Tailwind/HTMX/Chart.js)
│   └── cli/                     # Typer CLI (run-scrape, etc.)
├── tests/                       # mirrors src/carscraper structure
│   └── scrapers/<dealer>/fixtures/   # saved HTML snapshots per dealer
└── scripts/
    └── run_daily_scrape.bat     # Windows Task Scheduler entrypoint
```

### Layer responsibilities

- **`scrapers/`** — fetch + parse one dealer's listings into `CarListingDTO`
  objects. No DB access, no business logic. Each dealer module's only job is
  "given this dealer's site, produce a list of DTOs."
- **`services/`** — all business logic lives here: turning DTOs into DB rows,
  deduplication, updating `first_seen`/`last_seen`, recording price snapshots,
  computing aggregates (avg price per model, price trends). Services are the
  only layer that talks to both scrapers and the DB.
- **`db/`** — SQLAlchemy models and session/engine setup. No business logic —
  models describe data shape and relationships only.
- **`api/`** — FastAPI routers. Thin: validate input, call a service, return a
  schema. No scraping or business logic in routers.
- **`web/`** — Jinja2 templates and static assets. Renders data provided by
  `api/` (or directly via FastAPI routes that return HTML). No business logic.
- **`cli/`** — entrypoints for running scrapes (used by Task Scheduler and for
  manual runs). Thin wrappers around `services`/`scrapers`.

## Design Discipline (SoC / SRP)

This project previously suffered from God-classes and single-file
implementations. To avoid repeating that:

- **One scraper class per dealer.** Each dealer site gets its own module under
  `scrapers/dealers/`, implementing `BaseScraper`. A scraper's only
  responsibility is fetching and parsing — it must not write to the database or
  contain cross-dealer logic.
- **`CarListingDTO` is the normalization boundary.** Every scraper returns a
  list of `CarListingDTO` objects (a Pydantic model) regardless of how messy or
  dealer-specific the source HTML is. Anything dealer-specific stays inside
  that dealer's scraper module and is translated to the common DTO shape before
  leaving it.
- **No god classes/files.** If a module starts doing more than one of
  "fetch", "parse", "persist", "aggregate", or "render", split it. A scraper
  module may be split further (e.g. `dealers/volvo_example/fetch.py` +
  `parse.py`) if a single dealer's logic grows large — there's no requirement
  that a dealer is exactly one file, only that it's one *unit* behind
  `BaseScraper`.
- **Services mediate, routers don't.** API routers and CLI commands should
  never construct SQL/ORM queries directly or contain scraping logic — they
  call into `services/`.
- **New cross-cutting logic goes in `services/`, not in `scrapers/` or
  `api/`.** E.g. "mark listings not seen in the latest scrape as inactive" is a
  service-level concern that runs after all scrapers for a run complete — it is
  not part of any individual scraper.

## Conventions

- **Dealer scraper naming**: `scrapers/dealers/<dealer_slug>/` (or
  `<dealer_slug>.py` for simple cases), where `<dealer_slug>` is a short
  lowercase identifier for the dealer (e.g. `bilia_stockholm`). The same slug
  is used as the `Dealer.scraper_module` reference in the DB.
- **Fixture-based scraper tests**: each dealer has
  `tests/scrapers/<dealer_slug>/fixtures/*.html` — real (anonymized if needed)
  saved pages from that dealer's site. Tests run the scraper's parsing logic
  against these fixtures, not against the live site. When a dealer changes
  their site and the scraper breaks, update the fixture + scraper together.
- **Adding a new dealer** (high-level — a dedicated slash command will
  formalize this later):
  1. Save sample HTML from the dealer's listing/search pages as fixtures.
  2. Implement `BaseScraper` for the dealer, parsing fixtures into
     `CarListingDTO`s until tests pass.
  3. Register the dealer in the `scrapers/registry.py` and add a `Dealer` row.
  4. Verify against the live site with a manual `run-scrape --dealer=<slug>`.
- **Commands**: `ruff check .`, `black .`, `pytest`, `alembic upgrade head`,
  `python -m carscraper.cli run-scrape [--dealer=<slug>]`.

## Data Model Summary

- **`Dealer`** — `id`, `name`, `base_url`, `scraper_module` (slug), `enabled`.
- **`TrackedModel`** — `make`, `model`, optional `variant`/trim. Defines what
  the user wants scraped/surfaced; configured from the UI.
- **`CarListing`** — one row per distinct listing per dealer:
  `dealer_id`, `external_id`/`url` (stable natural key from the dealer's site),
  `make`, `model`, `variant`, `year`, `mileage`, `price`, `fuel_type`,
  `transmission`, `first_seen`, `last_seen`, `active` (false once a listing
  isn't seen in a scrape run — implies sold/removed).
- **`PriceSnapshot`** — `listing_id`, `price`, `scraped_at`. One row appended
  per scrape run (or per price change). This is what drives both per-listing
  price-history charts and avg-price-per-model aggregation queries.

## Workflow

Planning happens up front and produces GitHub issues on
[Braindrift/car-scraper](https://github.com/Braindrift/car-scraper).

### Ticket naming

Every ticket is titled `CAR-<n> <Title>`, where `<n>` is the GitHub issue
number it corresponds to — e.g. `CAR-3 Add BaseScraper and CarListingDTO` is
issue `#3` in `Braindrift/car-scraper`. Always use the `CAR-<n>` prefix when
referring to a ticket (commit subjects, branch names if used, closing
comments, code comments referencing a ticket) so tickets, commits, and issues
stay trivially cross-referenceable. Never drop or renumber the prefix, and
never invent a `CAR-<n>` that doesn't match the actual issue number.

Each issue body should include a **Definition of Done** section — a short
checklist of concrete, verifiable outcomes. `/batch` relies on this both to
scope the work and to report which items were actually verified.

### Implementing tickets

Run `/batch` to implement, test, commit, push, and close tickets end-to-end —
each ticket runs inside its own isolated subagent, sequentially (see
`.claude/commands/batch.md`). Accepts:
- `/batch CAR-4` — a single ticket
- `/batch CAR-3 to CAR-14` — an inclusive range
- `/batch CAR-3 CAR-7 CAR-12` — an explicit list
- `/batch all open CAR` — every open ticket, ascending

A batch stops immediately if any ticket comes back `BLOCKED`. Until a ticket
exists, or for ad-hoc work, follow the architecture and SoC/SRP conventions in
this file.

### Adding a new dealer scraper

No dedicated slash command yet — deliberately deferred until the first MVP
slice (one dealer, end-to-end) is working. Until then, follow the high-level
steps under "Adding a new dealer" in Conventions.

## Workspace

### Repo registry
Github repository: https://github.com/Braindrift/car-scraper
