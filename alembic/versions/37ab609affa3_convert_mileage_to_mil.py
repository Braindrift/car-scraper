"""convert mileage to mil

Data-only migration: `CarListing.mileage` was being stored in km (bilweb_se
converted its native "Mil:" reading to km, and kvd_se's `odometerReading` is
already km), but `services.stats.MILEAGE_BUCKETS` was designed assuming
mileage in Swedish mil (1 mil = 10 km) - the unit Swedish car listings
natively use. That mismatch put almost every listing in the open-ended
"30000+" bucket (e.g. a 120 610 km listing is far past a 30 000 km/mil
boundary either way, but as km it should sit in a ~12 000 mil bucket).

Both scrapers now emit `mileage` in mil (see CAR-23/CAR-16 follow-up: bilweb's
`_derive_mileage` no longer multiplies by 10, kvd's divides `odometerReading`
by 10). This migration converts existing stored values (km) to mil by
dividing by 10 and rounding to the nearest whole mil.

Revision ID: 37ab609affa3
Revises: 75b536ddef11
Create Date: 2026-06-16 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "37ab609affa3"
down_revision: str | Sequence[str] | None = "75b536ddef11"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KM_PER_MIL = 10


def upgrade() -> None:
    """Convert stored `mileage` values from km to mil (divide by 10, round)."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE car_listings "
            "SET mileage = CAST(ROUND(CAST(mileage AS FLOAT) / :km_per_mil) AS INTEGER) "
            "WHERE mileage IS NOT NULL"
        ),
        {"km_per_mil": _KM_PER_MIL},
    )


def downgrade() -> None:
    """Convert stored `mileage` values from mil back to km (multiply by 10)."""
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE car_listings SET mileage = mileage * :km_per_mil WHERE mileage IS NOT NULL"
        ),
        {"km_per_mil": _KM_PER_MIL},
    )
