from services.db import SessionLocal
from services.vehicle_service import VehicleService
from services.fuel_record_service import FuelRecordService
from services.exchange_rate import ExchangeRate
from datetime import datetime, date

# **********************************************
# --------------- MENU APLIKACE ----------------
# **********************************************

def print_main_menu():
    """
    Zobrazí hlavní menu aplikace
    """
    print("\x1b[2J")
    print("=== SIMPLE FLEET MANAGER ===")
    print("1 - Vozidla")
    print("2 - Tankování")
#    print("3 - Servis")
    print("\n0 - Konec")

def print_vehicle_menu():
    """
    Zobrazí menu pro vozidla
    """
    print("\n--- SPRÁVA VOZIDEL ---")
    print("1 - Seznam vozidel")
    print("2 - Přidat vozidlo")
    print("\n0 - Zpět")

def print_vehiclle_list_menu():
    """
    Zobrazí menu pro vozidlo
    """
    print("\nT - Zobrazit tankování | P - Přidat tankování | E - editovat vozidlo | D - Smazat vozidlo | 0 - Zpět")

def print_refueling_menu():
    """
    Zobrazí menu pro tankování
    """
    print("\n--- SPRÁVA TANKOVÁNÍ ---")
    print("1 - Přehled všech tankování")
    print("2 - Filtr dle vozidla")
    print("3 - Přidat tankování")
    print("\n0 - Zpět")

# **********************************************
# -------------- FUNKCE PRO MENU ---------------
# **********************************************
def show_main_menu():
    """
    Obsluha hlavního menu aplikace
    """
    while True:
        print_main_menu()
        choice = input("\nVyber akci: ").strip()

        if choice == "1":                                               # Vozidla
            print("\x1b[2J")
            show_vehicle_menu()
        elif choice == "2":                                             # Tankování                                    
            print("\x1b[2J")
            show_refueling_menu()
        elif choice == "0":                                             # Konec
            print("Končím")
            break
        else:
            print("Neplatná volba.")

def show_vehicle_menu():
    """
    Obsluha menu pro vozidla
    """
    
    session = SessionLocal()
    service = VehicleService(session)
    FuelService = FuelRecordService(session)

    try:
        while True:
            print_vehicle_menu()
            choice = input("\nVyber akci: ").strip()

            if choice == "1":                                                           # Seznam vozidel
                print("\x1b[2J")
                list_vehicles(service)
                vehicle_id = input("\nZadejte ID vozidla: ").strip()
                print("\x1b[2J")
                show_vehicle_details(service, vehicle_id)
                
                while True:
                    print_vehiclle_list_menu()
                    sub_choice = input("Vyber akci: ").strip().upper()
                    if sub_choice == "T":                                               # Tankování
                        list_fuel_records_for_vehicle(FuelService, vehicle_id)
                    elif sub_choice == "P":                                             # Přidat tankování
                        create_fuel_record_for_vehicle(FuelService, vehicle_id)
                    elif sub_choice == "E":                                             # Editovat vozidlo
                        edit_vehicle(service, vehicle_id)
                    elif sub_choice == "D":                                             # Smazat vozidlo   
                        pass
                    elif sub_choice == "0":
                        break
                    else:
                        print("Neplatná volba.")
            elif choice == "2":                                                         # Přidat vozidlo
                add_vehicle(service)
            elif choice == "0":                                                         # Zpět
                break
            else:
                print("Neplatná volba.")
    finally:
        session.close()

def show_refueling_menu():
    """
    Obsluha menu pro tankování
    """
    
    session = SessionLocal()
    FuelService = FuelRecordService(session)

    try:
        while True:
            print_refueling_menu()
            choice = input("\nVyber akci: ").strip()

            if choice == "1":                                                   # Všechna tankování
                print("\x1b[2J")
                list_fuel_records(FuelService)
            elif choice == "2":                                                 # Tankování pro vozidlo                                            
                print("\x1b[2J")
                vehicle_id = input("Zadejte ID vozidla: ").strip()
                list_fuel_records_for_vehicle(FuelService, vehicle_id)
            elif choice == "3":                                                 # Přidat tankování                       
                pass
            elif choice == "0":                                                 # Zpět           
                break
            else:
                print("Neplatná volba.")
    finally:
        session.close()

# **********************************************
# ------------- FUNKCE PRO VOZIDLA -------------
# **********************************************

def list_vehicles(service):
    """
    Vypíše seznam všech vozidel z databáze
    """
    vehicles = service.get_all_vehicles()

    if not vehicles:
        print("\nŽádná vozidla nenalezena.")
        return

    print("\nSeznam vozidel:\n")

    for v in vehicles:
        print(
            f"- ID: {v.id} | {v.brand} {v.model} | "
            f"SPZ: {v.license_plate or '-'} | "
            f"Barva: {v.color or '-'} | "
            f"Aktivní: {'ano' if v.is_active else 'ne'}"
        )

def edit_vehicle(service, vehicle_id):
    """
    Umožní editovat informace o vozidle
    """
    vehicle = service.get_vehicle(vehicle_id)

    if not vehicle:
        print("\nVozidlo nenalezeno.")
        return
    
    brand = input(f"Značka [{vehicle.brand}]: ").strip() or vehicle.brand
    model = input(f"Model [{vehicle.model}]: ").strip() or vehicle.model
    license_plate = input(f"SPZ [{vehicle.license_plate or '-'}]: ").strip() or vehicle.license_plate
    color = input(f"Barva [{vehicle.color or '-'}]: ").strip() or vehicle.color

    try:
        vehicle = service.edit_vehicle(
            vehicle_id=vehicle_id,
            brand=brand,
            model=model,
            license_plate=license_plate,
            color=color
        )
        print(f"\n✅ Vozidlo upraveno (ID: {vehicle.id})")

    except ValueError as e:
        print(f"\n❌ Chyba hodnoty: {e}")

    except Exception as e:
        print(f"\n❌ Neočekávaná chyba: {e}")

def show_vehicle_details(service, vehicle_id):
    """
    Zobrazí detailní informace o vozidle
    """
    vehicle = service.get_vehicle(vehicle_id)

    if not vehicle:
        print("\nVozidlo nenalezeno.")
        return

    print(f"\n--- Detail vozidla ID {vehicle.id} ---")
    print(f"Značka: {vehicle.brand}")
    print(f"Model: {vehicle.model}")
    print(f"SPZ: {vehicle.license_plate or '-'}")
    print(f"Barva: {vehicle.color or '-'}")
    print(f"Aktivní: {'ano' if vehicle.is_active else 'ne'}")

def add_vehicle(service):
    """
    Přidá do databáze nové vozidlo na základě uživatelského vstupu
    """
    
    print("\n--- Přidání vozidla ---")

    brand = input("Značka: ").strip()
    model = input("Model: ").strip()
    license_plate = input("SPZ (nepovinné): ").strip() or None
    color = input("Barva (nepovinné): ").strip() or None

    try:
        vehicle = service.create_vehicle(
            brand=brand,
            model=model,
            license_plate=license_plate,
            color=color
        )
        print(f"\n✅ Vozidlo vytvořeno (ID: {vehicle.id})")

    except ValueError as e:
        print(f"\n❌ Chyba hodnoty: {e}")

    except Exception as e:
        print(f"\n❌ Neočekávaná chyba: {e}")

def delete_vehicle(service):
    """
    Odstraní vozidlo z databáze dle zadaného ID
    """
    print("\n--- Odstranění vozidla ---")
    vehicle_id = input("Zadejte ID vozidla k odstranění: ").strip()

    if vehicle_id != "":
        delete_confirm = input(f"Opravdu chcete odstranit vozidlo s ID {vehicle_id}? (ano/ne): ").strip().lower()
    if delete_confirm == "ano":
        try:
            service.delete_vehicle(vehicle_id)
            print(f"\n✅ Vozidlo s ID {vehicle_id} bylo odstraněno.")
        except ValueError as e:
            print(f"\n❌ Chyba hodnoty: {e}")
        except Exception as e:
            print(f"\n❌ Neočekávaná chyba: {e}")

# **********************************************
# ------------ FUNKCE PRO TANKOVÁNÍ ------------
# **********************************************

def list_fuel_records(service):
    """
    Vypíše všechna tankování z databáze
    """
    fuel_records = service.get_all_fuel_records()

    if not fuel_records:
        print("\nŽádná tankování nenalezena.")
        return

    print("\nSeznam tankování:\n")

    for record in fuel_records:
        print(
            f"- ID: {record.id} | Vozidlo: {record.vehicle.brand} {record.vehicle.model} | "
            f"Datum: {record.refuel_date} | Čas: {record.refuel_time} | "
            f"Objem: {record.volume_liters} | Cena: {record.price_local}"
        )

def list_fuel_records_for_vehicle(service, vehicle_id):
    """
    Vypíše všechna tankování pro konkrétní vozidlo
    """
    fuel_records = service.get_fuel_records_for_vehicle(vehicle_id)

    if not fuel_records:
        print("\nŽádná tankování nenalezena.")
        return

    print("\nSeznam tankování:\n")

    for record in fuel_records:
        print(
            f"- ID: {record.id} | Vozidlo: {record.vehicle.brand} {record.vehicle.model} | "
            f"Datum: {record.refuel_date} | Čas: {record.refuel_time} | "
            f"Objem: {record.volume_liters} | Cena: {record.price_local}"
        )

def create_fuel_record_for_vehicle(service, vehicle_id):
    """
    Umožní přidat nové tankování pro konkrétní vozidlo
    """
    date_today = date_value = date.today().isoformat()
    time_now = datetime.now().strftime("%H:%M")

    print("\n--- Přidání tankování ---")
    
# Datum tankování
    while True:
        user_input = input(f"Datum tankování (rrrr-mm-dd) [{date_today}]: ").strip() or date_today
        try:
            refuel_date = datetime.strptime(user_input, "%Y-%m-%d").date().isoformat()
            break
        except ValueError:
            print("Zadáno neplatné datum. Zadekte datum ve formátu rrrr-mm-dd.")

# Čas tankování    
    while True:
        user_input = input(f"Zadej čas (hh:mm) [{time_now}]: ").strip() or time_now
        try:
            refuel_time = datetime.strptime(user_input, "%H:%M").time()
            break
        except ValueError:
            print("Zadán neplatný čas. Zadejte čas ve formátu (hh:mm).")

# Stav tachometru
# TODO - kontrola konzistence timestamp-odometr
    while True:
        try:
            odometer = int(input("Stav tachometru: ").strip())
            if odometer >= 0:
                break
            print("Stav tachometru nemůže být záporné číslo.")
        except ValueError:
            print("Zadán neplatný stav tachometru. Zadejte celé číslo.")

# Typ paliva
# TODO - zobrazení použitých možností a možnost přidat nový typ.
    while True:
        fuel_type = input("Typ paliva: ").strip()
        if fuel_type:
            break
        else:
            print("Typ paliva je povinná položka.")

# Tankováno litrů
    while True:
        try:
            volume_liters = float(input("Objem v litrech: ").strip().replace(",", "."))
            if volume_liters > 0:
                break
            print("Objem musí být větší než nula.")
        except ValueError:
            print("Zadán neplatný objem. Zadejte číslo (může být i desetinné).")

# Cena za litr
    while True:
        try:
            unit_price = float(input("Cena za litr: ").strip().replace(",", "."))
            if unit_price >= 0:
                break
            print("Cena za litr nemůže být záporná.")
        except ValueError:
            print("Zadána neplatná cena. Zadejte číslo (může být i desetinné).")

# Celková cena
    price_paid = unit_price * volume_liters

# Měna
    while True:
        currency_code = input("Měna [CZK]: ").strip() or "CZK"
        if len(currency_code) == 3 and currency_code.isalpha():
            break
        print("Zadejte třípísmenný kód měny (např. CZK, EUR, USD).")

# Výpis celkové ceny
    print(f"Celková cena: {price_paid} {currency_code}")

# Konverzce ceny na CZK
# TODO - místo pevně nastavené CZK umožnit nastavení měny v .env
    if currency_code != "CZK":  
        try:
            unit_price_local = ExchangeRate(refuel_date, currency_code, unit_price).ConvertToCZK()
        except Exception as e:
            print(f"Chyba při získávání kurzu: {e}")
            manual_fx_rate = input("Chcete zadat směnný kurz ručně? (ano/ne): ").strip().lower()
            if manual_fx_rate in ["ano", "a"]:
                while True:
                    try:
                        fx_rate = float(input(f"Zadejte hodnotu 1 {currency_code} v CZK: ").strip().replace(",", "."))
                        if fx_rate > 0:
                            unit_price_local = unit_price * fx_rate
                            break
                        print("Hodnota musí být větší než nula.")
                    except ValueError:
                        print("Zadaná hodnota je neplatná. Zadejte číslo (může být i desetinné).")
            else:            
                return
        price_local = unit_price_local * volume_liters
        print(f"Celková cena tankování: {price_local:.2f} CZK")
    else:
        unit_price_local = unit_price
        price_local = price_paid

# Platební metoda
    full_tank_input = input("Plná nádrž? (ano/ne): ").strip().lower()
    full_tank = full_tank_input == "ano"
    skipped_refuel_input = input("Vynechané tankování? (ano/ne): ").strip().lower()
    skipped_refuel = skipped_refuel_input == "ano"
# TODO - výpočet spotřeby
#    consumption = input("Spotřeba (nepovinné): ").strip() or None
    consumption = 0
    payment_method = input("Způsob platby (nepovinné): ").strip() or None
    station_name = input("Název čerpací stanice (nepovinné): ").strip() or None
    note = input("Poznámka (nepovinné): ").strip() or None

    try:
        fuel_record = service.create_fuel_record(
            vehicle_id=vehicle_id,
            refuel_date=refuel_date,
            refuel_time=refuel_time,
            odometer=odometer,
            fuel_type=fuel_type,
            volume_liters=volume_liters,
            unit_price=unit_price,
            price_paid=price_paid,
            currency_code=currency_code,
            unit_price_local=unit_price_local,
            price_local=price_local,
            payment_method=payment_method,
            station_name=station_name,
            full_tank=full_tank,
            skipped_refuel=skipped_refuel,
            consumption=consumption,
            note=note
        )
        print(f"\n✅ Tankování vytvořeno (ID: {fuel_record.id})")

    except ValueError as e: 
        print(f"\n❌ Chyba hodnoty: {e}")   