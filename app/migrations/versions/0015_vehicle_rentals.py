"""Půjčená vozidla a jednotlivá půjčení.

Revision ID: 0015_vehicle_rentals
Revises: 0014_default_intervals
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_vehicle_rentals"
down_revision = "0014_default_intervals"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("is_rental", sa.Boolean, nullable=False, server_default="0"))
    op.create_table(
        "vehicle_rentals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("provider", sa.String(100), nullable=False),
        sa.Column("date_from", sa.Date, nullable=False),
        sa.Column("date_to", sa.Date, nullable=True),
        sa.Column("odometer_from", sa.Integer, nullable=True),
        sa.Column("odometer_to", sa.Integer, nullable=True),
        sa.Column("price_paid", sa.DECIMAL(12, 3), nullable=True),
        sa.Column("currency_code", sa.CHAR(3), nullable=False),
        sa.Column("price_local", sa.DECIMAL(12, 3), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        mysql_charset="utf8mb4",
    )


def downgrade():
    op.drop_table("vehicle_rentals")
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("is_rental")
