"""Palivo a alternativní palivo vozidla.

Předvyplní se podle dosavadních tankování: dva nejčastější druhy paliva, hlavní je benzín / nafta
(u auta na benzín a LPG je LPG alternativní, i když se tankuje častěji).

Revision ID: 0020_vehicle_fuel
Revises: 0019_vehicle_lender
Create Date: 2026-11-24
"""
from collections import defaultdict

from alembic import op
import sqlalchemy as sa

revision = "0020_vehicle_fuel"
down_revision = "0019_vehicle_lender"
branch_labels = None
depends_on = None

CATEGORIES = ("Benzín", "Nafta", "LPG", "CNG", "Elektřina")


def upgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("fuel", sa.String(15), nullable=True))
        batch.add_column(sa.Column("alt_fuel", sa.String(15), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT vehicle_id, fuel_category, COUNT(*) FROM fuel_records"
        " WHERE fuel_category IS NOT NULL GROUP BY vehicle_id, fuel_category"))
    counts = defaultdict(list)
    for vehicle_id, category, count in rows:
        if category in CATEGORIES:
            counts[vehicle_id].append((count, category))
    for vehicle_id, items in counts.items():
        items.sort(key=lambda item: (-item[0], CATEGORIES.index(item[1])))
        top = [category for _, category in items[:2]]
        # benzín / nafta je hlavní palivo i u auta, které víc jezdí na LPG, CNG nebo elektřinu
        top.sort(key=lambda category: category not in ("Benzín", "Nafta"))
        fuel = top[0]
        alt = top[1] if len(top) > 1 else None
        bind.execute(sa.text("UPDATE vehicles SET fuel = :fuel, alt_fuel = :alt WHERE id = :id"),
                     {"fuel": fuel, "alt": alt, "id": vehicle_id})


def downgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("alt_fuel")
        batch.drop_column("fuel")
