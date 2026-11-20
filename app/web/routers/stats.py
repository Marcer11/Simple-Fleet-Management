"""Statistiky celého vozového parku (všechna vozidla, ke kterým má uživatel přístup)."""
from datetime import date

from fastapi import APIRouter, Depends, Request

from models import FuelRecord, ServiceRecord, Expense
from services.stats_service import StatsService
from web.common import visible_vehicles
from web.deps import get_db, get_current_user, render

router = APIRouter()


def parse_period(period, today=None):
    """'12m' (posledních 12 měsíců), 'YYYY' nebo 'all' -> (period, date_from, date_to)."""
    today = today or date.today()
    if period == "12m":
        return period, date(today.year - 1, today.month, 1), None
    if period.isdigit() and 1900 <= int(period) <= 2100:
        year = int(period)
        return period, date(year, 1, 1), date(year, 12, 31)
    return "all", None, None


def _years(db, vehicle_ids):
    years = {date.today().year}
    if vehicle_ids:
        for model, column in ((FuelRecord, FuelRecord.refuel_datetime), (ServiceRecord, ServiceRecord.service_date),
                              (Expense, Expense.expense_date)):
            for (value,) in db.query(column).filter(model.vehicle_id.in_(vehicle_ids)).distinct():
                years.add(value.year)
    return sorted(years, reverse=True)


@router.get("/stats")
async def fleet_stats(request: Request, period: str = "12m", user=Depends(get_current_user), db=Depends(get_db)):
    vehicles = visible_vehicles(db, user)
    period, date_from, date_to = parse_period(period)
    summary = StatsService(db).fleet_summary(vehicles, date_from, date_to)
    return render(request, "stats/fleet.html", summary=summary, period=period,
                  years=_years(db, [v.id for v in vehicles]), vehicles=vehicles)
