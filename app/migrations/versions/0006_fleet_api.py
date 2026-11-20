"""API pro Timeline: hash API klíče uživatele a autor tankování.

Revision ID: 0006_fleet_api
Revises: 0005_timeline
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_fleet_api"
down_revision = "0005_timeline"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("api_key_hash", sa.String(64), nullable=True))
        batch.add_column(sa.Column("api_key_created_at", sa.DateTime, nullable=True))
        batch.create_index("ix_users_api_key_hash", ["api_key_hash"], unique=True)
    with op.batch_alter_table("fuel_records") as batch:
        batch.add_column(sa.Column("created_by_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_fuel_records_created_by", "users", ["created_by_id"], ["id"],
                                 ondelete="SET NULL")
        batch.create_index("ix_fuel_records_created_by_id", ["created_by_id"])


def downgrade():
    with op.batch_alter_table("fuel_records") as batch:
        batch.drop_index("ix_fuel_records_created_by_id")
        batch.drop_constraint("fk_fuel_records_created_by", type_="foreignkey")
        batch.drop_column("created_by_id")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_api_key_hash")
        batch.drop_column("api_key_created_at")
        batch.drop_column("api_key_hash")
