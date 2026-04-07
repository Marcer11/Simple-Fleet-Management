from services.db import SessionLocal
from services.vehicle_service import VehicleService


def print_main_menu():
    """
    Zobrazí hlavní menu aplikace
    """
    print("\x1b[2J")
    print("=== SIMPLE FLEET MANAGER ===")
    print("1 - Vozidla")
    print("2 - Tankování")
    print("3 - Servis")
    print("\n0 - Konec")

def print_vehicle_menu():
    """
    Zobrazí menu pro vozidla
    """
    print("\n--- SPRÁVA VOZIDEL ---")
    print("1 - Seznam vozidel")
    print("2 - Přidat vozidlo")
    print("\n0 - Zpět")


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
        print(f"\n❌ Chyba: {e}")


def show_main_menu():
    """
    Zobrazí hlavní menu aplikace
    """

    while True:
        print_main_menu()
        choice = input("\nVyber akci: ").strip()

        if choice == "1":
            print("\x1b[2J")
            show_vehicle_menu()
        elif choice == "2":
            pass
        elif choice == "0":
            print("Končím")
            break
        else:
            print("Neplatná volba.")

def show_vehicle_menu():
    """
    Zobrazí menu pro vozidla
    """
    
    session = SessionLocal()
    service = VehicleService(session)

    try:
        while True:
            print_vehicle_menu()
            choice = input("\nVyber akci: ").strip()

            if choice == "1":
                print("\x1b[2J")
                list_vehicles(service)
            elif choice == "2":
                add_vehicle(service)
            elif choice == "0":
                break
            else:
                print("Neplatná volba.")
    finally:
        session.close()