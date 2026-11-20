"""Napojení na Timeline: API klíč uživatele a adresa čerpací stanice.

Revision ID: 0005_timeline
Revises: 0004_expense_validity
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_timeline"
down_revision = "0004_expense_validity"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("timeline_api_key", sa.String(100), nullable=True))
    with op.batch_alter_table("fuel_records") as batch:
        batch.add_column(sa.Column("station_address", sa.String(200), nullable=True))


def downgrade():
    with op.batch_alter_table("fuel_records") as batch:
        batch.drop_column("station_address")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("timeline_api_key")
