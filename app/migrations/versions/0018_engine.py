"""Objem motoru a výkon vozidla.

Revision ID: 0018_engine
Revises: 0017_rental_times
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0018_engine"
down_revision = "0017_rental_times"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("engine_volume", sa.Integer, nullable=True))
        batch.add_column(sa.Column("engine_power", sa.Integer, nullable=True))


def downgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("engine_power")
        batch.drop_column("engine_volume")
