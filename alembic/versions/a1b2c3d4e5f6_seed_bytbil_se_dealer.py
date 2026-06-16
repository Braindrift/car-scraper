"""seed bytbil.se dealer

Data-only migration (CAR-26): adds the `Dealer` row for the bytbil.se scraper
(`scraper_module="bytbil_se"`). There is no admin UI for `Dealer` rows yet, so
real dealer scrapers register themselves here (mirrors CAR-16/CAR-18's
seed migrations for kvd_se and bilweb_se).

Idempotent: `upgrade()` only inserts the row if no `Dealer` with
`scraper_module="bytbil_se"` already exists. `downgrade()` deletes that row.

Revision ID: a1b2c3d4e5f6
Revises: 37ab609affa3
Create Date: 2026-06-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "37ab609affa3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCRAPER_MODULE = "bytbil_se"

_dealers = sa.table(
    "dealers",
    sa.column("id", sa.Integer),
    sa.column("name", sa.String),
    sa.column("base_url", sa.String),
    sa.column("scraper_module", sa.String),
    sa.column("enabled", sa.Boolean),
)


def upgrade() -> None:
    """Insert the Bytbil `Dealer` row, unless one already exists."""
    bind = op.get_bind()

    existing = bind.execute(
        sa.select(_dealers.c.id).where(_dealers.c.scraper_module == _SCRAPER_MODULE)
    ).first()
    if existing is not None:
        return

    bind.execute(
        sa.insert(_dealers).values(
            name="Bytbil",
            base_url="https://www.bytbil.com",
            scraper_module=_SCRAPER_MODULE,
            enabled=True,
        )
    )


def downgrade() -> None:
    """Remove the Bytbil `Dealer` row."""
    bind = op.get_bind()
    bind.execute(sa.delete(_dealers).where(_dealers.c.scraper_module == _SCRAPER_MODULE))
