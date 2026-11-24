"""Pneumatiky: sady, přezutí, poškození.

Revision ID: 0009_tires
Revises: 0008_notes_prices_brands
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_tires"
down_revision = "0008_notes_prices_brands"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tire_sets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season", sa.String(15), nullable=False),
        sa.Column("manufacturer", sa.String(50), nullable=False),
        sa.Column("model", sa.String(50), nullable=True),
        sa.Column("size", sa.String(30), nullable=True),
        sa.Column("production_year", sa.Integer, nullable=True),
        sa.Column("dot", sa.String(10), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="4"),
        sa.Column("rim", sa.String(10), nullable=False, server_default=""),
        sa.Column("new_tread_mm", sa.DECIMAL(3, 1), nullable=True),
        sa.Column("purchase_date", sa.Date, nullable=True),
        sa.Column("expense_id", sa.Integer, sa.ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage_location", sa.String(100), nullable=True),
        sa.Column("retired_date", sa.Date, nullable=True),
        sa.Column("retired_reason", sa.String(200), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_tire_sets_vehicle_id", "tire_sets", ["vehicle_id"])
    op.create_table(
        "tire_changes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_date", sa.Date, nullable=False),
        sa.Column("odometer", sa.Integer, nullable=False),
        sa.Column("tire_set_id", sa.Integer, sa.ForeignKey("tire_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("place", sa.String(10), nullable=False, server_default="home"),
        sa.Column("service_record_id", sa.Integer,
                  sa.ForeignKey("service_records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("removed_tread_mm", sa.DECIMAL(3, 1), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_tire_changes_vehicle_date", "tire_changes", ["vehicle_id", "change_date"])
    op.create_index("ix_tire_changes_tire_set_id", "tire_changes", ["tire_set_id"])
    op.create_table(
        "tire_damages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tire_set_id", sa.Integer, sa.ForeignKey("tire_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("damage_date", sa.Date, nullable=False),
        sa.Column("odometer", sa.Integer, nullable=True),
        sa.Column("position", sa.String(20), nullable=True),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("expense_id", sa.Integer, sa.ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_tire_damages_vehicle_id", "tire_damages", ["vehicle_id"])
    op.create_index("ix_tire_damages_tire_set_id", "tire_damages", ["tire_set_id"])


def downgrade():
    op.drop_index("ix_tire_damages_tire_set_id", table_name="tire_damages")
    op.drop_index("ix_tire_damages_vehicle_id", table_name="tire_damages")
    op.drop_table("tire_damages")
    op.drop_index("ix_tire_changes_tire_set_id", table_name="tire_changes")
    op.drop_index("ix_tire_changes_vehicle_date", table_name="tire_changes")
    op.drop_table("tire_changes")
    op.drop_index("ix_tire_sets_vehicle_id", table_name="tire_sets")
    op.drop_table("tire_sets")
