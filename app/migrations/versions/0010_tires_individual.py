"""Pneumatiky jako samostatné položky (guma / pár / sada) nasazované na různá vozidla a pozice.

Převede sady (tire_sets) na pneumatiky, přezutí (tire_changes) na události přezutí s nasazením
na "všechna kola" a poškození (tire_damages); staré tabulky smaže.

Revision ID: 0010_tires_individual
Revises: 0009_tires
Create Date: 2026-11-25
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_tires_individual"
down_revision = "0009_tires"
branch_labels = None
depends_on = None


def _create_new_tables():
    op.create_table(
        "tires",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season", sa.String(15), nullable=False),
        sa.Column("manufacturer", sa.String(50), nullable=False),
        sa.Column("model", sa.String(50), nullable=True),
        sa.Column("size", sa.String(30), nullable=True),
        sa.Column("production_year", sa.Integer, nullable=True),
        sa.Column("dot", sa.String(10), nullable=True),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="2"),
        sa.Column("rim", sa.String(10), nullable=False, server_default=""),
        sa.Column("new_tread_mm", sa.DECIMAL(3, 1), nullable=True),
        sa.Column("purchase_date", sa.Date, nullable=True),
        sa.Column("price_paid", sa.DECIMAL(12, 3), nullable=True),
        sa.Column("currency_code", sa.CHAR(3), nullable=False, server_default="CZK"),
        sa.Column("price_local", sa.DECIMAL(12, 3), nullable=True),
        sa.Column("expense_id", sa.Integer, sa.ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True),
        sa.Column("storage_location", sa.String(100), nullable=True),
        sa.Column("retired_date", sa.Date, nullable=True),
        sa.Column("retired_reason", sa.String(200), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_tires_owner_id", "tires", ["owner_id"])
    op.create_table(
        "tire_swaps",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("swap_date", sa.Date, nullable=False),
        sa.Column("odometer", sa.Integer, nullable=False),
        sa.Column("place", sa.String(10), nullable=False, server_default="home"),
        sa.Column("service_record_id", sa.Integer,
                  sa.ForeignKey("service_records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("note", sa.Text, nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_tire_swaps_vehicle_date", "tire_swaps", ["vehicle_id", "swap_date"])
    op.create_table(
        "tire_mounts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tire_id", sa.Integer, sa.ForeignKey("tires.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.String(10), nullable=False, server_default="all"),
        sa.Column("swap_id", sa.Integer, sa.ForeignKey("tire_swaps.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mounted_date", sa.Date, nullable=False),
        sa.Column("mounted_km", sa.Integer, nullable=False),
        sa.Column("removed_swap_id", sa.Integer, sa.ForeignKey("tire_swaps.id", ondelete="SET NULL"), nullable=True),
        sa.Column("removed_date", sa.Date, nullable=True),
        sa.Column("removed_km", sa.Integer, nullable=True),
        sa.Column("removed_tread_mm", sa.DECIMAL(3, 1), nullable=True),
        mysql_charset="utf8mb4",
    )
    for column in ("tire_id", "vehicle_id", "swap_id", "removed_swap_id"):
        op.create_index(f"ix_tire_mounts_{column}", "tire_mounts", [column])
    op.create_table(
        "tire_defects",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("tire_id", sa.Integer, sa.ForeignKey("tires.id", ondelete="CASCADE"), nullable=False),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True),
        sa.Column("defect_date", sa.Date, nullable=False),
        sa.Column("odometer", sa.Integer, nullable=True),
        sa.Column("position", sa.String(20), nullable=True),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("expense_id", sa.Integer, sa.ForeignKey("expenses.id", ondelete="SET NULL"), nullable=True),
        mysql_charset="utf8mb4",
    )
    op.create_index("ix_tire_defects_tire_id", "tire_defects", ["tire_id"])
    op.create_index("ix_tire_defects_vehicle_id", "tire_defects", ["vehicle_id"])


def _migrate_data(conn):
    meta = sa.MetaData()
    old_sets = sa.Table("tire_sets", meta, autoload_with=conn)
    old_changes = sa.Table("tire_changes", meta, autoload_with=conn)
    old_damages = sa.Table("tire_damages", meta, autoload_with=conn)
    vehicles = sa.Table("vehicles", meta, autoload_with=conn)
    expenses = sa.Table("expenses", meta, autoload_with=conn)
    tires = sa.Table("tires", meta, autoload_with=conn)
    swaps = sa.Table("tire_swaps", meta, autoload_with=conn)
    mounts = sa.Table("tire_mounts", meta, autoload_with=conn)
    defects = sa.Table("tire_defects", meta, autoload_with=conn)

    owners = {r.id: r.owner_id for r in conn.execute(sa.select(vehicles.c.id, vehicles.c.owner_id))}
    tire_ids = {}
    for s in conn.execute(sa.select(old_sets)).mappings():
        owner = owners.get(s["vehicle_id"])
        if owner is None:
            continue  # vozidlo bez vlastníka - pneumatiku nelze nikomu přiřadit
        price = {"price_paid": None, "currency_code": "CZK", "price_local": None}
        if s["expense_id"]:
            e = conn.execute(sa.select(expenses).where(expenses.c.id == s["expense_id"])).mappings().first()
            if e:
                price = {"price_paid": e["price_paid"], "currency_code": e["currency_code"],
                         "price_local": e["price_local"]}
        result = conn.execute(tires.insert().values(
            owner_id=owner, season=s["season"], manufacturer=s["manufacturer"], model=s["model"], size=s["size"],
            production_year=s["production_year"], dot=s["dot"], quantity=s["quantity"], rim=s["rim"] or "",
            new_tread_mm=s["new_tread_mm"], purchase_date=s["purchase_date"], expense_id=s["expense_id"],
            storage_location=s["storage_location"], retired_date=s["retired_date"],
            retired_reason=s["retired_reason"], note=s["note"], **price))
        tire_ids[s["id"]] = result.inserted_primary_key[0]

    open_mount = {}  # vehicle_id -> id otevřeného nasazení
    rows = conn.execute(sa.select(old_changes).order_by(
        old_changes.c.vehicle_id, old_changes.c.change_date, old_changes.c.odometer, old_changes.c.id)).mappings()
    for c in rows:
        result = conn.execute(swaps.insert().values(
            vehicle_id=c["vehicle_id"], swap_date=c["change_date"], odometer=c["odometer"], place=c["place"],
            service_record_id=c["service_record_id"], note=c["note"]))
        swap_id = result.inserted_primary_key[0]
        previous = open_mount.pop(c["vehicle_id"], None)
        if previous is not None:
            conn.execute(mounts.update().where(mounts.c.id == previous).values(
                removed_swap_id=swap_id, removed_date=c["change_date"], removed_km=c["odometer"],
                removed_tread_mm=c["removed_tread_mm"]))
        tire_id = tire_ids.get(c["tire_set_id"])
        if tire_id is not None:
            result = conn.execute(mounts.insert().values(
                tire_id=tire_id, vehicle_id=c["vehicle_id"], position="all", swap_id=swap_id,
                mounted_date=c["change_date"], mounted_km=c["odometer"]))
            open_mount[c["vehicle_id"]] = result.inserted_primary_key[0]

    for d in conn.execute(sa.select(old_damages)).mappings():
        tire_id = tire_ids.get(d["tire_set_id"])
        if tire_id is not None:
            conn.execute(defects.insert().values(
                tire_id=tire_id, vehicle_id=d["vehicle_id"], defect_date=d["damage_date"], odometer=d["odometer"],
                position=d["position"], description=d["description"], expense_id=d["expense_id"]))


def upgrade():
    _create_new_tables()
    _migrate_data(op.get_bind())
    op.drop_table("tire_damages")
    op.drop_table("tire_changes")
    op.drop_table("tire_sets")


def downgrade():
    # data se zpět nepřevádějí - obnoví se jen prázdné tabulky z 0009
    for table in ("tire_defects", "tire_mounts", "tire_swaps", "tires"):
        op.drop_table(table)
    op.create_table(
        "tire_sets",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("season", sa.String(15), nullable=False),
        sa.Column("manufacturer", sa.String(50), nullable=False),
        sa.Column("model", sa.String(50)), sa.Column("size", sa.String(30)),
        sa.Column("production_year", sa.Integer), sa.Column("dot", sa.String(10)),
        sa.Column("quantity", sa.Integer, nullable=False, server_default="4"),
        sa.Column("rim", sa.String(10), nullable=False, server_default=""),
        sa.Column("new_tread_mm", sa.DECIMAL(3, 1)), sa.Column("purchase_date", sa.Date),
        sa.Column("expense_id", sa.Integer, sa.ForeignKey("expenses.id", ondelete="SET NULL")),
        sa.Column("storage_location", sa.String(100)), sa.Column("retired_date", sa.Date),
        sa.Column("retired_reason", sa.String(200)), sa.Column("note", sa.Text),
    )
    op.create_table(
        "tire_changes",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("change_date", sa.Date, nullable=False),
        sa.Column("odometer", sa.Integer, nullable=False),
        sa.Column("tire_set_id", sa.Integer, sa.ForeignKey("tire_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("place", sa.String(10), nullable=False, server_default="home"),
        sa.Column("service_record_id", sa.Integer, sa.ForeignKey("service_records.id", ondelete="SET NULL")),
        sa.Column("removed_tread_mm", sa.DECIMAL(3, 1)), sa.Column("note", sa.Text),
    )
    op.create_table(
        "tire_damages",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("vehicle_id", sa.Integer, sa.ForeignKey("vehicles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tire_set_id", sa.Integer, sa.ForeignKey("tire_sets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("damage_date", sa.Date, nullable=False),
        sa.Column("odometer", sa.Integer), sa.Column("position", sa.String(20)),
        sa.Column("description", sa.String(200), nullable=False),
        sa.Column("expense_id", sa.Integer, sa.ForeignKey("expenses.id", ondelete="SET NULL")),
    )
