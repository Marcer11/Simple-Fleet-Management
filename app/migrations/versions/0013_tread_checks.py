"""Průběžné kontroly hloubky dezénu (po kolech).

Revision ID: 0013_tread_checks
Revises: 0012_vehicle_tire_sizes
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_tread_checks"
down_revision = "0012_vehicle_tire_sizes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tire_tread_checks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("check_date", sa.Date, nullable=False),
        sa.Column("odometer", sa.Integer, nullable=False),
        sa.Column("note", sa.Text, nullable=True),
        sa.Column("created_by_id", sa.Integer, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_tire_tread_checks_vehicle_date", "tire_tread_checks", ["vehicle_id", "check_date"])
    op.create_table(
        "tire_tread_readings",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("check_id", sa.Integer, sa.ForeignKey("tire_tread_checks.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("tire_id", sa.Integer, sa.ForeignKey("tires.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("mount_id", sa.Integer, sa.ForeignKey("tire_mounts.id", ondelete="SET NULL"), nullable=True,
                  index=True),
        sa.Column("wheel", sa.String(5), nullable=False),
        sa.Column("tread_mm", sa.DECIMAL(3, 1), nullable=False),
        mysql_charset="utf8mb4",
    )


def downgrade():
    op.drop_table("tire_tread_readings")
    op.drop_index("ix_tire_tread_checks_vehicle_date", table_name="tire_tread_checks")
    op.drop_table("tire_tread_checks")
