"""Druh vozidla (auto / motorka), dezén při sundání po kolech, servis s více položkami.

Revision ID: 0011_vehicle_kind_treads
Revises: 0010_tires_individual
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0011_vehicle_kind_treads"
down_revision = "0010_tires_individual"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="car"))
    with op.batch_alter_table("tire_mounts") as batch:
        batch.add_column(sa.Column("removed_treads", sa.String(60), nullable=True))
    with op.batch_alter_table("service_records") as batch:
        batch.alter_column("service_type", existing_type=sa.String(50), type_=sa.String(255),
                           existing_nullable=False)


def downgrade():
    with op.batch_alter_table("service_records") as batch:
        batch.alter_column("service_type", existing_type=sa.String(255), type_=sa.String(50),
                           existing_nullable=False)
    with op.batch_alter_table("tire_mounts") as batch:
        batch.drop_column("removed_treads")
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("kind")
