"""Poznámky k vozidlu, pořizovací a prodejní cena, vazba paliva na pumpy.

Revision ID: 0008_notes_prices_brands
Revises: 0007_fuel_types
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_notes_prices_brands"
down_revision = "0007_fuel_types"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "vehicle_notes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note_datetime", sa.DateTime, nullable=False),
        sa.Column("odometer", sa.Integer, nullable=True),
        sa.Column("category", sa.String(40), nullable=True),
        sa.Column("text", sa.Text, nullable=True),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_vehicle_notes_vehicle_time", "vehicle_notes", ["vehicle_id", "note_datetime"])
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("purchase_price", sa.DECIMAL(12, 2), nullable=True))
        batch.add_column(sa.Column("sale_price", sa.DECIMAL(12, 2), nullable=True))
    with op.batch_alter_table("fuel_types") as batch:
        batch.add_column(sa.Column("station_brands", sa.String(255), nullable=True))


def downgrade():
    with op.batch_alter_table("fuel_types") as batch:
        batch.drop_column("station_brands")
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("sale_price")
        batch.drop_column("purchase_price")
    op.drop_index("ix_vehicle_notes_vehicle_time", table_name="vehicle_notes")
    op.drop_table("vehicle_notes")
