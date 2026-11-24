"""Čas půjčení a vrácení vozidla.

Revision ID: 0017_rental_times
Revises: 0016_insurance_claims
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_rental_times"
down_revision = "0016_insurance_claims"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vehicle_rentals") as batch:
        batch.add_column(sa.Column("time_from", sa.Time, nullable=True))
        batch.add_column(sa.Column("time_to", sa.Time, nullable=True))


def downgrade():
    with op.batch_alter_table("vehicle_rentals") as batch:
        batch.drop_column("time_to")
        batch.drop_column("time_from")
