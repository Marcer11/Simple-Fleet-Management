"""Náklady a najeté km po měsících i po letech za celé období (dříve jen posledních 36 měsíců)."""
from datetime import date

from models import Vehicle
from services.stats_service import StatsService
from test_web import register, add_vehicle, add_fuel, app, db  # noqa: F401


def test_costs_by_year_whole_history(app, db):
    client = register(app, "yearly@example.com")
    vid = add_vehicle(client)
    for day, km in [(date(2009, 5, 1), 10000), (date(2009, 9, 1), 11000), (date(2015, 3, 1), 60000),
                    (date(2026, 2, 1), 150000)]:
        assert add_fuel(client, vid, day, km, "40").status_code == 303

    summary = StatsService(db).vehicle_summary(vid)
    charts = summary["charts"]
    assert charts["monthly_labels"][0] == "2009-05"  # celé období, ne jen 36 měsíců
    assert charts["yearly_labels"][0] == "2009" and charts["yearly_labels"][-1] == str(date.today().year)
    assert len(charts["yearly_labels"]) == date.today().year - 2009 + 1
    assert charts["yearly_fuel"][0] == 3200 and sum(charts["yearly_fuel"]) == sum(charts["monthly_fuel"]) == 6400

    km = StatsService(db).odometer_charts(vid)
    assert km["monthly_km_labels"][0] == "2009-05" and km["yearly_km_labels"][0] == "2009"
    assert sum(km["yearly_km"]) == sum(km["monthly_km"])

    # dlouhé období začíná na pohledu po letech
    page = client.get(f"/vehicles/{vid}/stats?period=all").text
    assert 'data-chart-period="chart-monthly" data-period="year" aria-pressed="true"' in page
    assert 'data-chart-period="chart-monthly-km" data-period="year" aria-pressed="true"' in page
    assert "<th>Rok</th>" in page
    fleet = client.get("/stats?period=all").text
    assert 'data-chart-period="chart-monthly" data-period="year" aria-pressed="true"' in fleet
    # krátké období po měsících
    page = client.get(f"/vehicles/{vid}/stats?period=2026").text
    assert 'data-chart-period="chart-monthly" data-period="month" aria-pressed="true"' in page
