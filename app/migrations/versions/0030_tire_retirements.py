"""Vyřazení části sady pneumatik (jednotlivá kola). Dříve vyřazené pneumatiky dostanou záznam o vyřazení všech kusů.

Revision ID: 0030_tire_retirements
Revises: 0029_tire_kind
Create Date: 2026-11-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0030_tire_retirements"
down_revision = "0029_tire_kind"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tire_retirements",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tire_id", sa.Integer, sa.ForeignKey("tires.id", ondelete="CASCADE"), nullable=False),
        sa.Column("retire_date", sa.Date, nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("wheels", sa.String(30), nullable=True),
        sa.Column("reason", sa.String(200), nullable=True),
        sa.Column("swap_id", sa.Integer, sa.ForeignKey("tire_swaps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("odometer", sa.Integer, nullable=True),
    )
    op.create_index("ix_tire_retirements_tire_id", "tire_retirements", ["tire_id"])
    op.create_index("ix_tire_retirements_swap_id", "tire_retirements", ["swap_id"])
    op.execute("INSERT INTO tire_retirements (tire_id, retire_date, quantity, reason) "
               "SELECT id, retired_date, quantity, retired_reason FROM tires WHERE retired_date IS NOT NULL")


def downgrade():
    op.drop_index("ix_tire_retirements_swap_id", "tire_retirements")
    op.drop_index("ix_tire_retirements_tire_id", "tire_retirements")
    op.drop_table("tire_retirements")
