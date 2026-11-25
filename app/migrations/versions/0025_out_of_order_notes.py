"""Nepojízdnost vozidla se eviduje poznámkami ("Nepojízdné" / "Opět pojízdné"), ne u vozidla.

Vozidla označená jako nepojízdná dostanou poznámku "Nepojízdné" se stejným datem a důvodem.

Revision ID: 0025_out_of_order_notes
Revises: 0024_vehicle_out_of_order
Create Date: 2026-11-25
"""
from datetime import date, datetime

from alembic import op
import sqlalchemy as sa

revision = "0025_out_of_order_notes"
down_revision = "0024_vehicle_out_of_order"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, out_of_order_since, out_of_order_reason FROM vehicles WHERE out_of_order_since IS NOT NULL"))
    for vehicle_id, since, reason in rows.fetchall():
        day = date.fromisoformat(str(since)[:10])
        bind.execute(sa.text("INSERT INTO vehicle_notes (vehicle_id, note_datetime, category, text)"
                             " VALUES (:v, :t, 'Nepojízdné', :text)"),
                     {"v": vehicle_id, "t": datetime.combine(day, datetime.min.time()), "text": reason})
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_column("out_of_order_reason")
        batch.drop_column("out_of_order_since")


def downgrade():
    with op.batch_alter_table("vehicles") as batch:
        batch.add_column(sa.Column("out_of_order_since", sa.Date(), nullable=True))
        batch.add_column(sa.Column("out_of_order_reason", sa.String(200), nullable=True))
