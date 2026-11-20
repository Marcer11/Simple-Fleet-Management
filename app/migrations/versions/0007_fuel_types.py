"""Vlastní seznam paliv uživatele a druh paliva u tankování.

Revision ID: 0007_fuel_types
Revises: 0006_fleet_api
Create Date: 2026-11-20
"""
import re

from alembic import op
import sqlalchemy as sa

revision = "0007_fuel_types"
down_revision = "0006_fleet_api"
branch_labels = None
depends_on = None


def _guess(name):
    # kopie models.fuel_record.guess_fuel_category - migrace nemá záviset na budoucí podobě modelů
    text = (name or "").strip().lower()
    rules = (
        ("Elektřina", r"elektř|elektr|\bkwh\b|\bev\b|nabíj"),
        ("CNG", r"\bcng\b|zemní plyn"),
        ("LPG", r"\blpg\b|autoplyn"),
        ("Nafta", r"naft|diesel|dízl|\bd\b"),
        ("Benzín", r"benz[ií]n|natural|\bba\s?\d|super|\be5\b|\be10\b|\b9[58]\b|\b10[02]\b|petrol"),
    )
    for category, pattern in rules:
        if re.search(pattern, text):
            return category
    return None


def upgrade():
    op.create_table(
        "fuel_types",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(30), nullable=False),
        sa.Column("category", sa.String(15), nullable=True),
        sa.UniqueConstraint("user_id", "name", name="uq_fuel_types_user_name"),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_fuel_types_user_id", "fuel_types", ["user_id"])
    with op.batch_alter_table("fuel_records") as batch:
        batch.alter_column("fuel_type", existing_type=sa.String(15), type_=sa.String(30), existing_nullable=False)
        batch.add_column(sa.Column("fuel_category", sa.String(15), nullable=True))

    conn = op.get_bind()
    fuel = sa.table("fuel_records", sa.column("fuel_type", sa.String), sa.column("fuel_category", sa.String))
    for (name,) in conn.execute(sa.select(fuel.c.fuel_type).distinct()).fetchall():
        category = _guess(name)
        if category:
            conn.execute(fuel.update().where(fuel.c.fuel_type == name).values(fuel_category=category))


def downgrade():
    with op.batch_alter_table("fuel_records") as batch:
        batch.drop_column("fuel_category")
        batch.alter_column("fuel_type", existing_type=sa.String(30), type_=sa.String(15), existing_nullable=False)
    op.drop_index("ix_fuel_types_user_id", table_name="fuel_types")
    op.drop_table("fuel_types")
