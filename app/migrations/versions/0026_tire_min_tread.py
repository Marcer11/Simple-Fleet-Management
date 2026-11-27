"""Pneumatiky: vlastní minimum hloubky dezénu (prázdné = zákonné).

Revision ID: 0026_tire_min_tread
Revises: 0025_out_of_order_notes
Create Date: 2026-11-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0026_tire_min_tread"
down_revision = "0025_out_of_order_notes"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tires") as batch:
        batch.add_column(sa.Column("min_tread_mm", sa.DECIMAL(3, 1), nullable=True))


def downgrade():
    with op.batch_alter_table("tires") as batch:
        batch.drop_column("min_tread_mm")
