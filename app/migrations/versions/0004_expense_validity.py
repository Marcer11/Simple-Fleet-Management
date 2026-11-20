"""Platnost výdajů (dálniční známka, pojištění) a navázaná upomínka.

Revision ID: 0004_expense_validity
Revises: 0003_maintenance_and_expenses
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_expense_validity"
down_revision = "0003_maintenance_and_expenses"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("expenses") as batch:
        batch.add_column(sa.Column("valid_from", sa.Date, nullable=True))
        batch.add_column(sa.Column("valid_until", sa.Date, nullable=True))
        batch.add_column(sa.Column("reminder_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_expenses_reminder", "reminders", ["reminder_id"], ["id"],
                                 ondelete="SET NULL")
        batch.create_index("ix_expenses_reminder_id", ["reminder_id"])


def downgrade():
    with op.batch_alter_table("expenses") as batch:
        batch.drop_index("ix_expenses_reminder_id")
        batch.drop_constraint("fk_expenses_reminder", type_="foreignkey")
        batch.drop_column("reminder_id")
        batch.drop_column("valid_until")
        batch.drop_column("valid_from")
