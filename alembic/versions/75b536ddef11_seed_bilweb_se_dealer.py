"""seed bilweb.se dealer

Data-only migration (CAR-18): adds the `Dealer` row for the bilweb.se scraper
(`scraper_module="bilweb_se"`). There is no admin UI for `Dealer` rows yet, so
real dealer scrapers register themselves here (mirrors CAR-16's
`4c5d087408ae_seed_kvd_se_dealer.py`).

Idempotent: `upgrade()` only inserts the row if no `Dealer` with
`scraper_module="bilweb_se"` already exists. `downgrade()` deletes that row.

Revision ID: 75b536ddef11
Revises: 4c5d087408ae
Create Date: 2026-06-15 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "75b536ddef11"
down_revision: str | Sequence[str] | None = "4c5d087408ae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCRAPER_MODULE = "bilweb_se"

_dealers = sa.table(
    "dealers",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("base_url", sa.String),
    sa.column("scraper_module", sa.String),
    sa.column("enabled", sa.Boolean),
)


def upgrade() -> None:
    """Insert the Bilweb `Dealer` row, unless one already exists."""
    bind = op.get_bind()

    existing = bind.execute(
        sa.select(_dealers.c.id).where(_dealers.c.scraper_module == _SCRAPER_MODULE)
    ).first()
    if existing is not None:
        return

    bind.execute(
        sa.insert(_dealers).values(
            name="Bilweb",
            base_url="https://bilweb.se",
            scraper_module=_SCRAPER_MODULE,
            enabled=True,
        )
    )


def downgrade() -> None:
    """Remove the Bilweb `Dealer` row."""
    bind = op.get_bind()
    bind.execute(sa.delete(_dealers).where(_dealers.c.scraper_module == _SCRAPER_MODULE))
