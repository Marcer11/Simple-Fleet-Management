"""Povolené rozměry pneumatik vozidla (dle technického průkazu), kilometry při nákupu a prodeji.

Revision ID: 0012_vehicle_tire_sizes
Revises: 0011_vehicle_kind_treads
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_vehicle_tire_sizes"
down_revision = "0011_vehicle_kind_treads"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("tire_sizes", sa.String(500), nullable=True))
        batch.add_column(sa.Column("purchase_odometer", sa.Integer, nullable=True))
        batch.add_column(sa.Column("sale_odometer", sa.Integer, nullable=True))


def downgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("sale_odometer")
        batch.drop_column("purchase_odometer")
        batch.drop_column("tire_sizes")
