"""add car_listing last_viewed_at

CAR-14: track when the user last opened a listing's detail page, so the
dashboard can flag NEW/UPDATED listings since that point.

Revision ID: 031e54cbb913
Revises: 86511a487ec0
Create Date: 2026-06-14 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "031e54cbb913"
down_revision: str | Sequence[str] | None = "86511a487ec0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("car_listings", schema=None) as batch_op:
        batch_op.add_column(sa.Column("last_viewed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("car_listings", schema=None) as batch_op:
        batch_op.drop_column("last_viewed_at")
