from services.db import SessionLocal
from services.vehicle_service import VehicleService
from services.fuel_record_service import FuelRecordService

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
                        pass
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