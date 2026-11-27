"""Benzina je samostatná značka pump: paliva omezená na ORLEN dostanou i Benzinu, ať jdou tankovat jako dosud.

Revision ID: 0028_benzina_brand
Revises: 0027_expense_place
Create Date: 2026-11-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0028_benzina_brand"
down_revision = "0027_expense_place"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, station_brands FROM fuel_types WHERE station_brands IS NOT NULL")).fetchall()
    for row_id, brands in rows:
        items = [b for b in (brands or "").split(",") if b]
        lower = [b.lower() for b in items]
        if "orlen" in lower and "benzina" not in lower:
            text = ",".join(items + ["Benzina"])
            if len(text) <= 255:
                conn.execute(sa.text("UPDATE fuel_types SET station_brands = :b WHERE id = :id"), {"b": text, "id": row_id})


def downgrade():
    pass
