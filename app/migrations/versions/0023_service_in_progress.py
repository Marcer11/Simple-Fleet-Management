"""Servis: vozidlo je zatím v servisu (nevyzvednuto).

Revision ID: 0023_service_in_progress
Revises: 0022_service_duration
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0023_service_in_progress"
down_revision = "0022_service_duration"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("service_records") as batch:
        batch.add_column(sa.Column("in_progress", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("service_records") as batch:
        batch.drop_column("in_progress")
