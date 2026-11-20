#!/usr/bin/env python
"""
Správcovské příkazy.

    python app/manage.py create-user                 # vytvoří uživatele (zeptá se na údaje)
    python app/manage.py list-users
    python app/manage.py set-password <email>
    python app/manage.py assign-orphans <email>      # vozidla bez vlastníka přiřadí uživateli
    python app/manage.py deactivate-user <email>
"""
import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from services.db import SessionLocal  # noqa: E402
from services.errors import ValidationError  # noqa: E402
from services.user_service import UserService  # noqa: E402
from services.vehicle_service import VehicleService  # noqa: E402


def _ask_password():
    password = getpass.getpass("Heslo: ")
    confirm = getpass.getpass("Heslo znovu: ")
    return password, confirm


def _user_or_exit(service, email):
    user = service.get_by_email(email)
    if user is None:
        sys.exit(f"Uživatel {email} neexistuje.")
    return user


def main(argv=None):
    parser = argparse.ArgumentParser(description="Simple Fleet Manager - správa")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create-user", help="vytvoří nového uživatele")
    create.add_argument("--email")
    create.add_argument("--name")
    sub.add_parser("list-users", help="vypíše uživatele")
    pwd = sub.add_parser("set-password", help="nastaví uživateli nové heslo")
    pwd.add_argument("email")
    orphans = sub.add_parser("assign-orphans", help="vozidla bez vlastníka přiřadí uživateli")
    orphans.add_argument("email")
    deact = sub.add_parser("deactivate-user", help="zablokuje přihlášení uživatele")
    deact.add_argument("email")

    args = parser.parse_args(argv)
    session = SessionLocal()
    users = UserService(session)
    try:
        if args.command == "create-user":
            email = args.email or input("E-mail: ")
            name = args.name or input("Jméno: ")
            password, confirm = _ask_password()
            user = users.create_user(email, name, password, confirm)
            print(f"Uživatel {user.email} vytvořen (ID {user.id}).")

        elif args.command == "list-users":
            for user in users.list_users():
                state = "" if user.is_active else " [zablokován]"
                print(f"{user.id:>4}  {user.email:<35} {user.name}{state}")

        elif args.command == "set-password":
            user = _user_or_exit(users, args.email)
            password, confirm = _ask_password()
            users.change_password(user, None, password, confirm)
            print("Heslo změněno.")

        elif args.command == "assign-orphans":
            user = _user_or_exit(users, args.email)
            vehicles = VehicleService(session).get_orphan_vehicles()
            for vehicle in vehicles:
                vehicle.owner_id = user.id
                print(f"  {vehicle.display_name}")
            session.commit()
            print(f"Přiřazeno vozidel: {len(vehicles)}.")

        elif args.command == "deactivate-user":
            user = _user_or_exit(users, args.email)
            user.is_active = False
            session.commit()
            print(f"Uživatel {user.email} zablokován.")
    except ValidationError as e:
        sys.exit(f"Chyba: {e}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
