"""Výchozí schéma (vozidla a tankování) - odpovídá původnímu database.sql.

Tabulky se vytvoří jen pokud neexistují, takže migraci lze spustit
i na databázi, která byla založena ručně z database.sql.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None

MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def upgrade():
    existing = set(sa.inspect(op.get_bind()).get_table_names())

    if "vehicles" not in existing:
        op.create_table(
            "vehicles",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("brand", sa.String(50), nullable=False),
            sa.Column("model", sa.String(50), nullable=False),
            sa.Column("production_year", sa.Integer, nullable=True),
            sa.Column("color", sa.String(30), nullable=True),
            sa.Column("license_plate", sa.String(10), nullable=True),
            sa.Column("vin", sa.CHAR(17), nullable=True),
            sa.Column("note", sa.Text, nullable=True),
            sa.Column("purchase_date", sa.Date, nullable=True),
            sa.Column("sale_date", sa.Date, nullable=True),
            sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
            sa.Column("color_hex", sa.CHAR(7), nullable=False, server_default="#FFFFFF"),
            **MYSQL_OPTS,
        )

    if "fuel_records" not in existing:
        op.create_table(
            "fuel_records",
            sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
            sa.Column("vehicle_id", sa.Integer,
                      sa.ForeignKey("vehicles.id", name="fk_fuel_records_vehicle",
                                    ondelete="CASCADE", onupdate="CASCADE"),
                      nullable=False),
            sa.Column("refuel_datetime", sa.DateTime, nullable=False),
            sa.Column("odometer", sa.Integer, nullable=False),
            sa.Column("fuel_type", sa.String(15), nullable=False),
            sa.Column("volume_liters", sa.DECIMAL(7, 2), nullable=False),
            sa.Column("unit_price", sa.DECIMAL(10, 3), nullable=True),
            sa.Column("price_paid", sa.DECIMAL(12, 3), nullable=False),
            sa.Column("currency_code", sa.CHAR(3), nullable=False, server_default="CZK"),
            sa.Column("unit_price_local", sa.DECIMAL(10, 3), nullable=True),
            sa.Column("price_local", sa.DECIMAL(12, 3), nullable=True),
            sa.Column("payment_method", sa.String(20), nullable=True),
            sa.Column("station_name", sa.String(100), nullable=True),
            sa.Column("full_tank", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("skipped_refuel", sa.Boolean, nullable=False, server_default=sa.false()),
            sa.Column("consumption", sa.DECIMAL(5, 2), nullable=True),
            sa.Column("note", sa.Text, nullable=True),
            **MYSQL_OPTS,
        )
        op.create_index("idx_fuel_records_vehicle_id", "fuel_records", ["vehicle_id"])
        op.create_index("idx_fuel_records_refuel_daterite", "fuel_records", ["refuel_datetime"])


def downgrade():
    op.drop_table("fuel_records")
    op.drop_table("vehicles")
