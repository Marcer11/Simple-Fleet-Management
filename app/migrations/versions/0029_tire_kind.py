"""Pneumatiky: pro auto, nebo motorku. Stávající se zařadí podle vozidel, na kterých byly nasazené.

Revision ID: 0029_tire_kind
Revises: 0028_benzina_brand
Create Date: 2026-11-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0029_tire_kind"
down_revision = "0028_benzina_brand"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("tires") as batch:
        batch.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="car"))
    op.execute("UPDATE tires SET kind = 'moto' WHERE id IN (SELECT tm.tire_id FROM tire_mounts tm "
               "JOIN vehicles v ON v.id = tm.vehicle_id WHERE v.kind = 'moto')")


def downgrade():
    with op.batch_alter_table("tires") as batch:
        batch.drop_column("kind")
