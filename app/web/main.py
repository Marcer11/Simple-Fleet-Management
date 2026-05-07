from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from services.db import SessionLocal
from services.vehicle_service import VehicleService
from services.fuel_record_service import FuelRecordService
from services.exchange_rate import ExchangeRate
from datetime import datetime, date
from pathlib import Path

app = FastAPI(title="Simple Fleet Manager")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


# **********************************************
# --------- POMOCNÉ FUNKCE ---------
# **********************************************

def get_db():
    """Vrátí session pro komunikaci s databází"""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def format_datetime(dt):
    """Formátuje datetime pro zobrazení"""
    if dt:
        return dt.strftime("%d.%m.%Y %H:%M")
    return ""


def format_date(d):
    """Formátuje date pro zobrazení"""
    if d:
        return d.strftime("%d.%m.%Y")
    return ""


# **********************************************
# --------- DOMOVSKÁ STRÁNKA ---------
# **********************************************

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Domovská stránka"""
    session = SessionLocal()
    try:
        vehicle_service = VehicleService(session)
        fuel_service = FuelRecordService(session)
        
        vehicles_count = len(vehicle_service.get_all_vehicles())
        fuel_records_count = len(fuel_service.get_all_fuel_records())
        
        return templates.TemplateResponse("index.html", {
            "request": request,
            "vehicles_count": vehicles_count,
            "fuel_records_count": fuel_records_count
        })
    finally:
        session.close()


# **********************************************
# --------- VOZIDLA - ROUTE ---------
# **********************************************

@app.get("/vehicles", response_class=HTMLResponse)
async def list_vehicles(request: Request):
    """Seznam všech vozidel"""
    session = SessionLocal()
    try:
        service = VehicleService(session)
        vehicles = service.get_all_vehicles()
        
        return templates.TemplateResponse("vehicles.html", {
            "request": request,
            "vehicles": vehicles
        })
    finally:
        session.close()


@app.get("/vehicles/add", response_class=HTMLResponse)
async def add_vehicle_form(request: Request):
    """Formulář pro přidání vozidla"""
    return templates.TemplateResponse("add_vehicle.html", {"request": request})


@app.post("/vehicles/add")
async def add_vehicle_post(
    request: Request,
    brand: str = Form(...),
    model: str = Form(...),
    license_plate: str = Form(default=""),
    color: str = Form(default="")
):
    """Přidá nové vozidlo do databáze"""
    session = SessionLocal()
    try:
        service = VehicleService(session)
        
        license_plate = license_plate.strip() or None
        color = color.strip() or None
        
        vehicle = service.create_vehicle(
            brand=brand.strip(),
            model=model.strip(),
            license_plate=license_plate,
            color=color
        )
        
        return RedirectResponse(url=f"/vehicles/{vehicle.id}", status_code=303)
    except ValueError as e:
        return templates.TemplateResponse("add_vehicle.html", {
            "request": request,
            "error": str(e),
            "brand": brand,
            "model": model,
            "license_plate": license_plate,
            "color": color
        })
    finally:
        session.close()


@app.get("/vehicles/{vehicle_id}", response_class=HTMLResponse)
async def vehicle_detail(request: Request, vehicle_id: int):
    """Detail vozidla"""
    session = SessionLocal()
    try:
        vehicle_service = VehicleService(session)
        fuel_service = FuelRecordService(session)
        
        vehicle = vehicle_service.get_vehicle(vehicle_id)
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vozidlo nenalezeno")
        
        fuel_records = fuel_service.get_fuel_records_for_vehicle(vehicle_id)
        
        return templates.TemplateResponse("vehicle_detail.html", {
            "request": request,
            "vehicle": vehicle,
            "fuel_records": fuel_records,
            "format_datetime": format_datetime
        })
    finally:
        session.close()


@app.get("/vehicles/{vehicle_id}/edit", response_class=HTMLResponse)
async def edit_vehicle_form(request: Request, vehicle_id: int):
    """Formulář pro editaci vozidla"""
    session = SessionLocal()
    try:
        service = VehicleService(session)
        vehicle = service.get_vehicle(vehicle_id)
        
        if not vehicle:
            raise HTTPException(status_code=404, detail="Vozidlo nenalezeno")
        
        return templates.TemplateResponse("edit_vehicle.html", {
            "request": request,
            "vehicle": vehicle
        })
    finally:
        session.close()


@app.post("/vehicles/{vehicle_id}/edit")
async def edit_vehicle_post(
    request: Request,
    vehicle_id: int,
    brand: str = Form(...),
    model: str = Form(...),
    license_plate: str = Form(default=""),
    color: str = Form(default="")
):
    """Uloží změny vozidla"""
    session = SessionLocal()
    try:
        service = VehicleService(session)
        
        license_plate = license_plate.strip() or None
        color = color.strip() or None
        
        service.edit_vehicle(
            vehicle_id=vehicle_id,
            brand=brand.strip(),
            model=model.strip(),
            license_plate=license_plate,
            color=color
        )
        
        return RedirectResponse(url=f"/vehicles/{vehicle_id}", status_code=303)
    except ValueError as e:
        vehicle = service.get_vehicle(vehicle_id)
        return templates.TemplateResponse("edit_vehicle.html", {
            "request": request,
            "vehicle": vehicle,
            "error": str(e)
        })
    finally:
        session.close()


@app.post("/vehicles/{vehicle_id}/activate")
async def activate_vehicle(vehicle_id: int):
    """Aktivuje vozidlo"""
    session = SessionLocal()
    try:
        service = VehicleService(session)
        service.activate_vehicle(vehicle_id)
        return RedirectResponse(url=f"/vehicles/{vehicle_id}", status_code=303)
    finally:
        session.close()


@app.post("/vehicles/{vehicle_id}/deactivate")
async def deactivate_vehicle(vehicle_id: int):
    """Deaktivuje vozidlo"""
    session = SessionLocal()
    try:
        service = VehicleService(session)
        service.deactivate_vehicle(vehicle_id)
        return RedirectResponse(url=f"/vehicles/{vehicle_id}", status_code=303)
    finally:
        session.close()


@app.post("/vehicles/{vehicle_id}/delete")
async def delete_vehicle_post(vehicle_id: int):
    """Smaže vozidlo"""
    session = SessionLocal()
    try:
        service = VehicleService(session)
        service.delete_vehicle(vehicle_id)
        return RedirectResponse(url="/vehicles", status_code=303)
    finally:
        session.close()


# **********************************************
# --------- TANKOVÁNÍ - ROUTE ---------
# **********************************************

@app.get("/fuel-records", response_class=HTMLResponse)
async def list_fuel_records(request: Request):
    """Seznam všech tankování"""
    session = SessionLocal()
    try:
        fuel_service = FuelRecordService(session)
        fuel_records = fuel_service.get_all_fuel_records()
        
        return templates.TemplateResponse("fuel_records.html", {
            "request": request,
            "fuel_records": fuel_records,
            "format_datetime": format_datetime
        })
    finally:
        session.close()


@app.get("/fuel-records/add", response_class=HTMLResponse)
async def add_fuel_record_form(request: Request, vehicle_id: int = None):
    """Formulář pro přidání tankování"""
    session = SessionLocal()
    try:
        vehicle_service = VehicleService(session)
        vehicles = vehicle_service.get_all_vehicles()
        
        today = date.today().isoformat()
        now = datetime.now().strftime("%H:%M")
        
        return templates.TemplateResponse("add_fuel_record.html", {
            "request": request,
            "vehicles": vehicles,
            "vehicle_id": vehicle_id,
            "today": today,
            "now": now
        })
    finally:
        session.close()


@app.post("/fuel-records/add")
async def add_fuel_record_post(
    request: Request,
    vehicle_id: int = Form(...),
    refuel_date: str = Form(...),
    refuel_time: str = Form(...),
    odometer: int = Form(...),
    fuel_type: str = Form(...),
    volume_liters: float = Form(...),
    unit_price: float = Form(...),
    currency_code: str = Form(default="CZK"),
    full_tank: bool = Form(default=False),
    skipped_refuel: bool = Form(default=False),
    payment_method: str = Form(default=""),
    station_name: str = Form(default=""),
    note: str = Form(default="")
):
    """Přidá nové tankování do databáze"""
    session = SessionLocal()
    try:
        fuel_service = FuelRecordService(session)
        vehicle_service = VehicleService(session)
        
        try:
            refuel_datetime = datetime.strptime(f"{refuel_date} {refuel_time}", "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError("Neplatné datum nebo čas")
        
        price_paid = unit_price * volume_liters
        
        if currency_code != "CZK":
            try:
                refuel_date_obj = datetime.strptime(refuel_date, "%Y-%m-%d").date()
                unit_price_local = ExchangeRate(refuel_date_obj, currency_code, unit_price).ConvertToCZK()
            except Exception:
                unit_price_local = unit_price
        else:
            unit_price_local = unit_price
        
        price_local = unit_price_local * volume_liters
        
        fuel_record = fuel_service.create_fuel_record(
            vehicle_id=vehicle_id,
            refuel_datetime=refuel_datetime,
            odometer=odometer,
            fuel_type=fuel_type.strip(),
            volume_liters=volume_liters,
            unit_price=unit_price,
            price_paid=price_paid,
            currency_code=currency_code.strip().upper(),
            unit_price_local=unit_price_local,
            price_local=price_local,
            payment_method=payment_method.strip() or None,
            station_name=station_name.strip() or None,
            full_tank=full_tank,
            skipped_refuel=skipped_refuel,
            consumption=None,
            note=note.strip() or None
        )
        
        return RedirectResponse(url=f"/vehicles/{vehicle_id}", status_code=303)
    
    except ValueError as e:
        vehicles = vehicle_service.get_all_vehicles()
        today = date.today().isoformat()
        now = datetime.now().strftime("%H:%M")
        
        return templates.TemplateResponse("add_fuel_record.html", {
            "request": request,
            "vehicles": vehicles,
            "vehicle_id": vehicle_id,
            "today": today,
            "now": now,
            "error": str(e)
        })
    finally:
        session.close()
