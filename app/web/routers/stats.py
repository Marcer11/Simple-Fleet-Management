"""Statistiky celého vozového parku (všechna vozidla, ke kterým má uživatel přístup)."""
from datetime import date
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request

from models import FuelRecord, ServiceRecord, Expense
from services.stats_service import StatsService
from web.common import visible_vehicles
from web.deps import get_db, get_current_user, render

router = APIRouter()


def _date(value):
    try:
        day = date.fromisoformat(value or "")
    except ValueError:
        return None
    return day if 1900 <= day.year <= 2100 else None


def parse_period(period, today=None, date_from=None, date_to=None):
    """'12m' (posledních 12 měsíců), 'YYYY', 'all' nebo 'custom' (rozsah date_from - date_to, ISO texty;
    prázdné = bez omezení) -> (period, date_from, date_to)."""
    today = today or date.today()
    if period == "custom" or (period is None and (date_from or date_to)):
        start, end = _date(date_from), _date(date_to)
        if start and end and end < start:
            start, end = end, start
        return "custom", start, end
    period = period or "12m"
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


def period_query(period, date_from, date_to):
    """Parametry odkazu se stejným obdobím (např. ze statistik všech vozidel do statistik vozidla)."""
    if period != "custom":
        return urlencode({"period": period})
    return urlencode({"period": "custom", **({"date_from": date_from.isoformat()} if date_from else {}),
                      **({"date_to": date_to.isoformat()} if date_to else {})})


@router.get("/stats")
async def fleet_stats(request: Request, period: Optional[str] = None, date_from: Optional[str] = None,
                      date_to: Optional[str] = None, user=Depends(get_current_user), db=Depends(get_db)):
    vehicles = visible_vehicles(db, user)
    period, date_from, date_to = parse_period(period, None, date_from, date_to)
    summary = StatsService(db).fleet_summary(vehicles, date_from, date_to)
    return render(request, "stats/fleet.html", summary=summary, period=period,
                  date_from=date_from, date_to=date_to, period_query=period_query(period, date_from, date_to),
                  years=_years(db, [v.id for v in vehicles]), vehicles=vehicles)
