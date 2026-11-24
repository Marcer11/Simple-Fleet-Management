"""Univerzální servisní intervaly uživatele; prodaná vozidla jsou neaktivní.

Revision ID: 0014_default_intervals
Revises: 0013_tread_checks
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_default_intervals"
down_revision = "0013_tread_checks"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "default_service_intervals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
                  index=True),
        sa.Column("service_type", sa.String(50), nullable=False),
        sa.Column("vehicle_kind", sa.String(10), nullable=True),
        sa.Column("interval_months", sa.Integer, nullable=True),
        sa.Column("interval_km", sa.Integer, nullable=True),
        mysql_charset="utf8mb4",
    )
    # vozidlo s datem prodeje už nemá být mezi aktivními
    op.execute("UPDATE vehicles SET is_active = 0 WHERE sale_date IS NOT NULL AND sale_date <= CURRENT_DATE")


def downgrade():
    op.drop_table("default_service_intervals")
