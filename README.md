# CarScraper 2.0

Personal tool for tracking used-car listings from a curated set of Swedish car
dealer websites. Runs as a daily batch job and presents results through a
local web dashboard.

See `CLAUDE.md` for architecture, conventions, and design discipline.

## Getting started

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
```

## Development commands

- `ruff check .` — lint
- `black .` — format
- `pytest` — run tests
- `alembic upgrade head` — apply DB migrations
- `python -m carscraper.cli run-scrape [--dealer=<slug>]` — run a scrape
