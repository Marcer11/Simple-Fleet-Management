"""Servis, pravidelný servis, upomínky a výdaje.

Revision ID: 0003_maintenance_and_expenses
Revises: 0002_users_and_sharing
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_maintenance_and_expenses"
down_revision = "0002_users_and_sharing"
branch_labels = None
depends_on = None

MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def _vehicle_fk(table):
    return sa.Column("vehicle_id", sa.Integer,
                     sa.ForeignKey("vehicles.id", name=f"fk_{table}_vehicle", ondelete="CASCADE"),
                     nullable=False)


def upgrade():
    op.create_table(
        "service_records",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        _vehicle_fk("service_records"),
        sa.Column("service_date", sa.Date, nullable=False),
        sa.Column("odometer", sa.Integer, nullable=True),
        sa.Column("service_type", sa.String(50), nullable=False),
        sa.Column("place", sa.String(100), nullable=True),
        sa.Column("price_paid", sa.DECIMAL(12, 3), nullable=True),
        sa.Column("currency_code", sa.CHAR(3), nullable=False, server_default="CZK"),
        sa.Column("price_local", sa.DECIMAL(12, 3), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        **MYSQL_OPTS,
    )
    op.create_index("ix_service_records_vehicle_id", "service_records", ["vehicle_id"])

    op.create_table(
        "service_intervals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        _vehicle_fk("service_intervals"),
        sa.Column("service_type", sa.String(50), nullable=False),
        sa.Column("interval_months", sa.Integer, nullable=True),
        sa.Column("interval_km", sa.Integer, nullable=True),
        sa.Column("start_date", sa.Date, nullable=True),
        sa.Column("start_odometer", sa.Integer, nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        **MYSQL_OPTS,
    )
    op.create_index("ix_service_intervals_vehicle_id", "service_intervals", ["vehicle_id"])

    op.create_table(
        "reminders",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        _vehicle_fk("reminders"),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("due_date", sa.Date, nullable=True),
        sa.Column("due_odometer", sa.Integer, nullable=True),
        sa.Column("repeat", sa.String(10), nullable=False, server_default="none"),
        sa.Column("repeat_km", sa.Integer, nullable=True),
        sa.Column("notify_days_before", sa.Integer, nullable=False, server_default="14"),
        sa.Column("notify_km_before", sa.Integer, nullable=False, server_default="500"),
        sa.Column("is_done", sa.Boolean, nullable=False, server_default=sa.false()),
        **MYSQL_OPTS,
    )
    op.create_index("ix_reminders_vehicle_id", "reminders", ["vehicle_id"])

    op.create_table(
        "expenses",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        _vehicle_fk("expenses"),
        sa.Column("expense_date", sa.Date, nullable=False),
        sa.Column("category", sa.String(30), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("odometer", sa.Integer, nullable=True),
        sa.Column("price_paid", sa.DECIMAL(12, 3), nullable=False),
        sa.Column("currency_code", sa.CHAR(3), nullable=False, server_default="CZK"),
        sa.Column("price_local", sa.DECIMAL(12, 3), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        **MYSQL_OPTS,
    )
    op.create_index("ix_expenses_vehicle_id", "expenses", ["vehicle_id"])


def downgrade():
    for table in ("expenses", "reminders", "service_intervals", "service_records"):
        op.drop_index(f"ix_{table}_vehicle_id", table_name=table)
        op.drop_table(table)
