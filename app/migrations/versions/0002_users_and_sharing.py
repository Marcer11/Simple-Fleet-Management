"""Uživatelé, vlastnictví a sdílení vozidel.

- tabulka users
- vehicles.owner_id (existující vozidla zůstanou bez vlastníka - přiřaďte je
  příkazem `python app/manage.py assign-orphans <email>`)
- tabulka vehicle_shares
- SPZ a VIN už nejsou globálně unikátní (různí uživatelé mohou evidovat
  stejné vozidlo, např. po prodeji)

Revision ID: 0002_users_and_sharing
Revises: 0001_baseline
Create Date: 2026-11-20
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_users_and_sharing"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None

MYSQL_OPTS = {"mysql_engine": "InnoDB", "mysql_charset": "utf8mb4", "mysql_collate": "utf8mb4_unicode_ci"}


def _unique_names(inspector, table, column):
    """Názvy unikátních omezení/indexů nad jedním sloupcem."""
    names = set()
    for uc in inspector.get_unique_constraints(table):
        if uc.get("column_names") == [column] and uc.get("name"):
            names.add(uc["name"])
    for ix in inspector.get_indexes(table):
        if ix.get("unique") and ix.get("column_names") == [column] and ix.get("name"):
            names.add(ix["name"])
    return names


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("email", name="uq_users_email"),
        **MYSQL_OPTS,
    )

    inspector = sa.inspect(op.get_bind())
    plate_uniques = _unique_names(inspector, "vehicles", "license_plate")
    vin_uniques = _unique_names(inspector, "vehicles", "vin")
    existing_indexes = {ix["name"] for ix in inspector.get_indexes("vehicles")}

    with op.batch_alter_table("vehicles") as batch:
        for name in sorted(plate_uniques | vin_uniques):
            if name in existing_indexes:
                batch.drop_index(name)
            else:
                batch.drop_constraint(name, type_="unique")
        batch.add_column(sa.Column("owner_id", sa.Integer, nullable=True))
        batch.create_foreign_key("fk_vehicles_owner", "users", ["owner_id"], ["id"], ondelete="SET NULL")
        batch.create_index("ix_vehicles_owner_id", ["owner_id"])
        batch.create_index("ix_vehicles_license_plate", ["license_plate"])
        batch.create_index("ix_vehicles_vin", ["vin"])

    op.create_table(
        "vehicle_shares",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer,
                  sa.ForeignKey("vehicles.id", name="fk_vehicle_shares_vehicle", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("user_id", sa.Integer,
                  sa.ForeignKey("users.id", name="fk_vehicle_shares_user", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("role", sa.String(10), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("vehicle_id", "user_id", name="uq_vehicle_shares_vehicle_user"),
        **MYSQL_OPTS,
    )
    op.create_index("ix_vehicle_shares_user_id", "vehicle_shares", ["user_id"])


def downgrade():
    op.drop_index("ix_vehicle_shares_user_id", table_name="vehicle_shares")
    op.drop_table("vehicle_shares")
    with op.batch_alter_table("vehicles") as batch:
        batch.drop_index("ix_vehicles_vin")
        batch.drop_index("ix_vehicles_license_plate")
        batch.drop_index("ix_vehicles_owner_id")
        batch.drop_constraint("fk_vehicles_owner", type_="foreignkey")
        batch.drop_column("owner_id")
    op.drop_table("users")
