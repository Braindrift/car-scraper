"""add car_listing discarded

Add a `discarded` flag so the user can set a listing aside ("not interested",
or de-clutter an inactive one) without deleting it. Discarded listings are
still scraped/updated and still count in stats; they're hidden from the main
dashboard list and surfaced on the Discarded page instead.

Revision ID: c3a9f1d2e4b7
Revises: b44edba46cca
Create Date: 2026-06-14 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9f1d2e4b7"
down_revision: str | Sequence[str] | None = "b44edba46cca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("car_listings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "discarded",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.create_index("ix_car_listings_discarded", ["discarded"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("car_listings", schema=None) as batch_op:
        batch_op.drop_index("ix_car_listings_discarded")
        batch_op.drop_column("discarded")
