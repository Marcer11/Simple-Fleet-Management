"""Vozidlo: nepojízdné (od kdy, důvod).

Revision ID: 0024_vehicle_out_of_order
Revises: 0023_service_in_progress
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0024_vehicle_out_of_order"
down_revision = "0023_service_in_progress"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("out_of_order_since", sa.Date(), nullable=True))
        batch.add_column(sa.Column("out_of_order_reason", sa.String(200), nullable=True))


def downgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("out_of_order_reason")
        batch.drop_column("out_of_order_since")
