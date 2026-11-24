"""Koho je půjčené vozidlo (půjčovna / od koho) - u vozidla místo u jednotlivého půjčení.

Hodnota se převezme z posledního půjčení vozidla; u půjčení zůstane (nepovinná) jen pro historii.

Revision ID: 0019_vehicle_lender
Revises: 0018_engine
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0019_vehicle_lender"
down_revision = "0018_engine"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("lender", sa.String(100), nullable=True))
    op.execute(
        "UPDATE vehicles SET lender = ("
        " SELECT r.provider FROM vehicle_rentals r WHERE r.vehicle_id = vehicles.id"
        " ORDER BY r.date_from DESC, r.id DESC LIMIT 1)"
        " WHERE is_rental = 1"
    )
    with op.batch_alter_table("vehicle_rentals") as batch:
        batch.alter_column("provider", existing_type=sa.String(100), nullable=True)


def downgrade():
    op.execute("UPDATE vehicle_rentals SET provider = '' WHERE provider IS NULL")
    with op.batch_alter_table("vehicle_rentals") as batch:
        batch.alter_column("provider", existing_type=sa.String(100), nullable=False)
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("lender")
