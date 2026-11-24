"""Pojistné plnění u servisu a výdajů.

Revision ID: 0016_insurance_claims
Revises: 0015_vehicle_rentals
Create Date: 2026-11-24
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_insurance_claims"
down_revision = "0015_vehicle_rentals"
branch_labels = None
depends_on = None

TABLES = ("service_records", "expenses")


def upgrade():
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("insurance_claim", sa.Boolean, nullable=False, server_default="0"))
            batch.add_column(sa.Column("insurer", sa.String(100), nullable=True))
            batch.add_column(sa.Column("policy_number", sa.String(50), nullable=True))
            batch.add_column(sa.Column("claim_number", sa.String(50), nullable=True))
            batch.add_column(sa.Column("insurance_paid", sa.DECIMAL(12, 3), nullable=True))


def downgrade():
    for table in TABLES:
        with op.batch_alter_table(table) as batch:
            for column in ("insurance_paid", "claim_number", "policy_number", "insurer", "insurance_claim"):
                batch.drop_column(column)
