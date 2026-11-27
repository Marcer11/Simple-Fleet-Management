"""Výdaje: místo (myčka, parkoviště, prodejna…) pro přehled míst.

Revision ID: 0027_expense_place
Revises: 0026_tire_min_tread
Create Date: 2026-11-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0027_expense_place"
down_revision = "0026_tire_min_tread"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("expenses") as batch:
        batch.add_column(sa.Column("place", sa.String(100), nullable=True))


def downgrade():
    with op.batch_alter_table("expenses") as batch:
        batch.drop_column("place")
