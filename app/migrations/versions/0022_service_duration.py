"""Servis: čas předání, vyzvednutí (datum, čas) a km při vyzvednutí.

Revision ID: 0022_service_duration
Revises: 0021_vignette_leap_year
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0022_service_duration"
down_revision = "0021_vignette_leap_year"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("service_records") as batch:
        batch.add_column(sa.Column("service_time", sa.Time(), nullable=True))
        batch.add_column(sa.Column("date_to", sa.Date(), nullable=True))
        batch.add_column(sa.Column("time_to", sa.Time(), nullable=True))
        batch.add_column(sa.Column("odometer_to", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("service_records") as batch:
        batch.drop_column("odometer_to")
        batch.drop_column("time_to")
        batch.drop_column("date_to")
        batch.drop_column("service_time")
