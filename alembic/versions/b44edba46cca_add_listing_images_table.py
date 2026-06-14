"""add listing_images table

CAR-15: store images downloaded for a listing (local static path + carousel
position) so the listing detail page can render an image carousel.

Revision ID: b44edba46cca
Revises: 031e54cbb913
Create Date: 2026-06-14 21:03:47.270722

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b44edba46cca"
down_revision: str | Sequence[str] | None = "031e54cbb913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "listing_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("listing_id", sa.Integer(), nullable=False),
        sa.Column("local_path", sa.String(length=500), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["listing_id"], ["car_listings.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("listing_id", "position", name="uq_listing_images_listing_position"),
    )
    with op.batch_alter_table("listing_images", schema=None) as batch_op:
        batch_op.create_index(
            "ix_listing_images_listing_id_position",
            ["listing_id", "position"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("listing_images", schema=None) as batch_op:
        batch_op.drop_index("ix_listing_images_listing_id_position")

    op.drop_table("listing_images")
