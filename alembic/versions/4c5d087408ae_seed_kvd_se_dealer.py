"""seed kvd.se dealer

Data-only migration (CAR-16): adds the `Dealer` row for the kvd.se scraper
(`scraper_module="kvd_se"`). There is no admin UI for `Dealer` rows yet, so
real dealer scrapers register themselves here.

Idempotent: `upgrade()` only inserts the row if no `Dealer` with
`scraper_module="kvd_se"` already exists. `downgrade()` deletes that row.

Revision ID: 4c5d087408ae
Revises: c3a9f1d2e4b7
Create Date: 2026-06-14 23:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c5d087408ae"
down_revision: str | Sequence[str] | None = "c3a9f1d2e4b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCRAPER_MODULE = "kvd_se"

_dealers = sa.table(
    "dealers",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("base_url", sa.String),
    sa.column("scraper_module", sa.String),
    sa.column("enabled", sa.Boolean),
)


def upgrade() -> None:
    """Insert the KVD `Dealer` row, unless one already exists."""
    bind = op.get_bind()

    existing = bind.execute(
        sa.select(_dealers.c.id).where(_dealers.c.scraper_module == _SCRAPER_MODULE)
    ).first()
    if existing is not None:
        return

    bind.execute(
        sa.insert(_dealers).values(
            name="KVD",
            base_url="https://www.kvd.se",
            scraper_module=_SCRAPER_MODULE,
            enabled=True,
        )
    )


def downgrade() -> None:
    """Remove the KVD `Dealer` row."""
    bind = op.get_bind()
    bind.execute(sa.delete(_dealers).where(_dealers.c.scraper_module == _SCRAPER_MODULE))
