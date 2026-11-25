"""Roční dálniční známka přes 29. únor platí 366 dní.

Dříve se konec platnosti počítal vždy jako 365 dní, takže známka, jejíž období zahrnuje 29. únor,
končila o den dřív (19.11.2023 -> 17.11.2024 místo 18.11.2024). Opraví se uložené známky
a k nim vytvořené upomínky konce platnosti.

Revision ID: 0021_vignette_leap_year
Revises: 0020_vehicle_fuel
Create Date: 2026-11-25
"""
import calendar
from datetime import date, timedelta

from alembic import op
import sqlalchemy as sa

revision = "0021_vignette_leap_year"
down_revision = "0020_vehicle_fuel"
branch_labels = None
depends_on = None

VIGNETTE_CATEGORY = "Dálniční známka"


def _date(value):
    return date.fromisoformat(str(value)[:10]) if value is not None else None


def _includes_leap_day(start, end):
    return any(calendar.isleap(year) and start <= date(year, 2, 29) <= end
               for year in range(start.year, end.year + 1))


def upgrade():
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, valid_from, valid_until, reminder_id FROM expenses"
        " WHERE category = :category AND valid_from IS NOT NULL AND valid_until IS NOT NULL"),
        {"category": VIGNETTE_CATEGORY}).fetchall()
    for expense_id, valid_from, valid_until, reminder_id in rows:
        start, end = _date(valid_from), _date(valid_until)
        if (end - start).days + 1 != 365 or not _includes_leap_day(start, end):
            continue
        fixed = end + timedelta(days=1)
        bind.execute(sa.text("UPDATE expenses SET valid_until = :fixed WHERE id = :id"),
                     {"fixed": fixed, "id": expense_id})
        if reminder_id is not None:
            bind.execute(sa.text("UPDATE reminders SET due_date = :fixed WHERE id = :id AND due_date = :old"),
                         {"fixed": fixed, "old": end, "id": reminder_id})


def downgrade():
    pass  # oprava dat, nevrací se
