import re
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from models import Vehicle, VehicleShare, FuelRecord, ServiceRecord, Expense, VehicleNote
from models.vehicle import ROLE_OWNER, ROLE_EDITOR, ROLE_VIEWER, ROLE_LEVELS, SHARE_ROLES, VEHICLE_KINDS, KIND_CAR
from services.errors import ValidationError, NotFoundError, PermissionDeniedError
from services.pricing import to_decimal, Q2
from services.user_service import normalize_email

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
VIN_RE = re.compile(r"^[A-HJ-NPR-Z0-9]{17}$")

# Pole, která lze u vozidla nastavit
VEHICLE_FIELDS = (
    "brand", "model", "production_year", "color", "color_hex", "license_plate",
    "vin", "note", "purchase_date", "sale_date", "is_active", "purchase_price", "sale_price", "kind",
    "tire_sizes", "purchase_odometer", "sale_odometer", "is_rental", "engine_volume", "engine_power",
    "lender", "fuel", "alt_fuel",
)


def normalize_plate(value):
    if value is None:
        return None
    value = re.sub(r"[\s-]", "", str(value)).upper()
    return value or None


class VehicleService:
    def __init__(self, session):
        self.session = session

    # ------------------------------------------------------------------
    # Původní rozhraní (používá i konzolová aplikace)
    # ------------------------------------------------------------------

    def get_all_vehicles(self):
        return self.session.query(Vehicle).order_by(Vehicle.id).all()

    def get_vehicle(self, vehicle_id):
        return (self.session.query(Vehicle)
                .filter(Vehicle.id == vehicle_id)
                .first())

    def create_vehicle(self, brand, model, license_plate=None, color=None, owner_id=None, **extra):
        data = {"brand": brand, "model": model, "license_plate": license_plate, "color": color, **extra}
        data = self._validate(data)

        vehicle = Vehicle(owner_id=owner_id, **data)
        if vehicle.color_hex is None:
            vehicle.color_hex = "#FFFFFF"
        if vehicle.is_active is None:
            vehicle.is_active = True
        if vehicle.is_sold:
            vehicle.is_active = False
        self.session.add(vehicle)
        self._commit()
        return vehicle

    def delete_vehicle(self, vehicle_id):
        vehicle = self.get_vehicle(vehicle_id)
        if not vehicle:
            raise ValueError("Vozidlo s daným ID nebylo nalezeno.")
        self.session.delete(vehicle)
        self.session.commit()

    def edit_vehicle(self, vehicle_id, brand=None, model=None, license_plate=None, color=None, is_active=None):
        """Mění jen předané hodnoty (None = beze změny). Pro úplnou úpravu viz update_vehicle()."""
        vehicle = self.get_vehicle(vehicle_id)
        if not vehicle:
            raise ValueError("Vozidlo s daným ID nebylo nalezeno.")

        changes = {
            key: value for key, value in {
                "brand": brand, "model": model, "license_plate": license_plate,
                "color": color, "is_active": is_active,
            }.items() if value is not None
        }
        return self.update_vehicle(vehicle, changes)

    def activate_vehicle(self, vehicle_id):
        self.edit_vehicle(vehicle_id, is_active=True)

    def deactivate_vehicle(self, vehicle_id):
        self.edit_vehicle(vehicle_id, is_active=False)

    # ------------------------------------------------------------------
    # Úprava a validace
    # ------------------------------------------------------------------

    def update_vehicle(self, vehicle, data):
        """Nastaví všechna předaná pole - i na None (tím jde hodnotu smazat)."""
        current = {field: getattr(vehicle, field) for field in VEHICLE_FIELDS}
        current.update(data)
        validated = self._validate(current)
        sold_before = vehicle.sale_date
        for key in data:
            setattr(vehicle, key, validated[key])
        if vehicle.is_sold and vehicle.sale_date != sold_before:
            vehicle.is_active = False  # zapsaný prodej vozidlo vyřadí z aktivních
        self._commit()
        return vehicle

    def _validate(self, data):
        data = {key: value for key, value in data.items() if key in VEHICLE_FIELDS}
        errors = []

        for key in ("brand", "model", "color", "note", "lender"):
            if key in data and isinstance(data[key], str):
                data[key] = data[key].strip() or None

        if "is_rental" in data:
            data["is_rental"] = bool(data["is_rental"])
        if not data.get("brand") or not data.get("model"):
            errors.append("Značka a model jsou povinné.")
        if "kind" in data:
            data["kind"] = data["kind"] or KIND_CAR
            if data["kind"] not in VEHICLE_KINDS:
                errors.append("Neplatný druh vozidla.")
        if data.get("brand") and len(data["brand"]) > 50:
            errors.append("Značka může mít nejvýše 50 znaků.")
        if data.get("model") and len(data["model"]) > 50:
            errors.append("Model může mít nejvýše 50 znaků.")
        if data.get("color") and len(data["color"]) > 30:
            errors.append("Barva může mít nejvýše 30 znaků.")
        from models.fuel_record import FUEL_CATEGORIES
        for key in ("fuel", "alt_fuel"):
            if key in data:
                data[key] = (data[key] or "").strip() or None
                if data[key] is not None and data[key] not in FUEL_CATEGORIES:
                    errors.append("Neznámý druh paliva.")
        if data.get("alt_fuel") and data.get("alt_fuel") == data.get("fuel"):
            errors.append("Alternativní palivo musí být jiné než hlavní.")
        if data.get("alt_fuel") and not data.get("fuel"):
            errors.append("K alternativnímu palivu vyberte i hlavní palivo.")
        if data.get("lender") and len(data["lender"]) > 100:
            errors.append("Koho auto je: nejvýše 100 znaků.")

        if "license_plate" in data:
            data["license_plate"] = normalize_plate(data["license_plate"])
            if data["license_plate"] and len(data["license_plate"]) > 10:
                errors.append("SPZ může mít nejvýše 10 znaků.")

        if data.get("vin"):
            data["vin"] = re.sub(r"\s", "", data["vin"]).upper()
            if not VIN_RE.match(data["vin"]):
                errors.append("VIN musí mít 17 znaků (písmena bez I, O, Q a číslice).")
        elif "vin" in data:
            data["vin"] = None

        if data.get("color_hex"):
            if not HEX_RE.match(data["color_hex"]):
                errors.append("Barva musí být ve formátu #RRGGBB.")
            else:
                data["color_hex"] = data["color_hex"].upper()

        if "tire_sizes" in data:
            lines = re.split(r"[\r\n;]+", data["tire_sizes"] or "")
            sizes = []
            for line in lines:
                line = re.sub(r"\s+", " ", line).strip()
                if line and line.lower() not in (s.lower() for s in sizes):
                    sizes.append(line)
            data["tire_sizes"] = "\n".join(sizes) or None
            if data["tire_sizes"] and len(data["tire_sizes"]) > 500:
                errors.append("Rozměry pneumatik mohou mít nejvýše 500 znaků.")

        year = data.get("production_year")
        if year is not None and not (1901 <= int(year) <= date.today().year + 1):
            errors.append("Neplatný rok výroby.")

        for key, label, limit in (("engine_volume", "Objem motoru", 20_000), ("engine_power", "Výkon", 2_000)):
            if data.get(key) is not None and not (0 <= int(data[key]) <= limit):
                errors.append(f"{label} musí být mezi 0 a {limit}.")

        for key, label in (("purchase_price", "Pořizovací cena"), ("sale_price", "Prodejní cena")):
            if key in data:
                data[key] = to_decimal(data[key], Q2)
                if data[key] is not None and not (0 <= data[key] < Decimal("10000000000")):
                    errors.append(f"{label} musí být kladné číslo.")

        for key, label in (("purchase_odometer", "Stav tachometru při nákupu"),
                           ("sale_odometer", "Stav tachometru při prodeji")):
            if data.get(key) is not None and not (0 <= int(data[key]) < 10_000_000):
                errors.append(f"{label} musí být kladné číslo.")
        if (data.get("purchase_odometer") is not None and data.get("sale_odometer") is not None
                and data["sale_odometer"] < data["purchase_odometer"]):
            errors.append("Kilometry při prodeji nemohou být menší než při nákupu.")

        purchase, sale = data.get("purchase_date"), data.get("sale_date")
        if purchase and sale and sale < purchase:
            errors.append("Datum prodeje nemůže být před datem nákupu.")

        if errors:
            raise ValidationError(" ".join(errors), errors)
        return data

    def _commit(self):
        try:
            self.session.commit()
        except IntegrityError as e:
            self.session.rollback()
            raise ValidationError("Záznam se nepodařilo uložit - porušení integrity dat.") from e

    # ------------------------------------------------------------------
    # Přístupová práva (víceuživatelský režim)
    # ------------------------------------------------------------------

    def get_role(self, vehicle, user):
        """Vrátí roli uživatele k vozidlu (owner/editor/viewer) nebo None."""
        if user is None or vehicle is None:
            return None
        if vehicle.owner_id == user.id:
            return ROLE_OWNER
        share = (self.session.query(VehicleShare)
                 .filter(VehicleShare.vehicle_id == vehicle.id, VehicleShare.user_id == user.id)
                 .first())
        return share.role if share else None

    def get_vehicle_for_user(self, vehicle_id, user, min_role=ROLE_VIEWER):
        """Vrátí vozidlo, pokud k němu má uživatel alespoň danou roli."""
        vehicle = self.get_vehicle(vehicle_id)
        role = self.get_role(vehicle, user)
        if vehicle is None or role is None:
            raise NotFoundError("Vozidlo nenalezeno.")
        if ROLE_LEVELS[role] < ROLE_LEVELS[min_role]:
            raise PermissionDeniedError("K této akci nemáte oprávnění.")
        return vehicle

    def _accessible_query(self, user):
        shared_ids = (self.session.query(VehicleShare.vehicle_id)
                      .filter(VehicleShare.user_id == user.id))
        return self.session.query(Vehicle).filter(
            or_(Vehicle.owner_id == user.id, Vehicle.id.in_(shared_ids))
        )

    def get_vehicles_for_user(self, user, only_active=False):
        query = self._accessible_query(user)
        if only_active:
            query = query.filter(Vehicle.is_active.is_(True),
                                 or_(Vehicle.sale_date.is_(None), Vehicle.sale_date > date.today()))
        vehicles = query.order_by(Vehicle.is_active.desc(), Vehicle.brand, Vehicle.model).all()
        if only_active:  # vrácené půjčené vozidlo není aktivní
            vehicles = [v for v in vehicles if not v.is_returned]
        return vehicles

    def get_roles_for_user(self, user):
        """{vehicle_id: role} pro všechna vozidla dostupná uživateli."""
        roles = {v.id: ROLE_OWNER for v in self.session.query(Vehicle).filter(Vehicle.owner_id == user.id)}
        for share in self.session.query(VehicleShare).filter(VehicleShare.user_id == user.id):
            roles.setdefault(share.vehicle_id, share.role)
        return roles

    def get_accessible_ids(self, user, min_role=ROLE_VIEWER):
        return [vid for vid, role in self.get_roles_for_user(user).items()
                if ROLE_LEVELS[role] >= ROLE_LEVELS[min_role]]

    # ------------------------------------------------------------------
    # Sdílení
    # ------------------------------------------------------------------

    def get_shares(self, vehicle):
        return (self.session.query(VehicleShare)
                .filter(VehicleShare.vehicle_id == vehicle.id)
                .order_by(VehicleShare.created_at)
                .all())

    def share_vehicle(self, vehicle, email, role=ROLE_VIEWER):
        from services.user_service import UserService

        if role not in SHARE_ROLES:
            raise ValidationError("Neplatná role.")
        target = UserService(self.session).get_by_email(normalize_email(email))
        if target is None:
            raise ValidationError("Uživatel s tímto e-mailem není registrován.")
        if target.id == vehicle.owner_id:
            raise ValidationError("Vlastníkovi vozidla nelze vozidlo sdílet.")

        share = (self.session.query(VehicleShare)
                 .filter(VehicleShare.vehicle_id == vehicle.id, VehicleShare.user_id == target.id)
                 .first())
        if share:
            share.role = role
        else:
            share = VehicleShare(vehicle_id=vehicle.id, user_id=target.id, role=role)
            self.session.add(share)
        self._commit()
        return share

    def _get_share(self, vehicle, share_id):
        share = self.session.get(VehicleShare, share_id)
        if share is None or share.vehicle_id != vehicle.id:
            raise NotFoundError("Sdílení nenalezeno.")
        return share

    def update_share_role(self, vehicle, share_id, role):
        if role not in SHARE_ROLES:
            raise ValidationError("Neplatná role.")
        share = self._get_share(vehicle, share_id)
        share.role = role
        self._commit()
        return share

    def remove_share(self, vehicle, share_id):
        share = self._get_share(vehicle, share_id)
        self.session.delete(share)
        self.session.commit()

    def leave_vehicle(self, vehicle, user):
        """Uživatel sám ukončí sdílení vozidla, které mu někdo nasdílel."""
        share = (self.session.query(VehicleShare)
                 .filter(VehicleShare.vehicle_id == vehicle.id, VehicleShare.user_id == user.id)
                 .first())
        if share is None:
            raise ValidationError("Toto vozidlo s vámi není sdíleno.")
        self.session.delete(share)
        self.session.commit()

    def transfer_ownership(self, vehicle, new_owner_share_id):
        """Předá vozidlo uživateli, se kterým je sdíleno; původní vlastník zůstane jako editor."""
        share = self._get_share(vehicle, new_owner_share_id)
        old_owner_id = vehicle.owner_id
        new_owner_id = share.user_id
        self.session.delete(share)
        self.session.flush()
        vehicle.owner_id = new_owner_id
        if old_owner_id is not None:
            self.session.add(VehicleShare(vehicle_id=vehicle.id, user_id=old_owner_id, role=ROLE_EDITOR))
        self._commit()

    # ------------------------------------------------------------------
    # Pomocné výpočty
    # ------------------------------------------------------------------

    def get_current_odometer(self, vehicle_id):
        """Nejvyšší známý stav tachometru ze všech záznamů vozidla."""
        values = [
            self.session.query(func.max(FuelRecord.odometer)).filter(FuelRecord.vehicle_id == vehicle_id).scalar(),
            self.session.query(func.max(ServiceRecord.odometer)).filter(ServiceRecord.vehicle_id == vehicle_id).scalar(),
            self.session.query(func.max(Expense.odometer)).filter(Expense.vehicle_id == vehicle_id).scalar(),
            self.session.query(func.max(VehicleNote.odometer)).filter(VehicleNote.vehicle_id == vehicle_id).scalar(),
        ]
        from models import TireTreadCheck
        values.append(self.session.query(func.max(TireTreadCheck.odometer))
                      .filter(TireTreadCheck.vehicle_id == vehicle_id).scalar())
        values.append(self.session.query(func.max(ServiceRecord.odometer_to))
                      .filter(ServiceRecord.vehicle_id == vehicle_id).scalar())
        from models import VehicleRental
        values.append(self.session.query(func.max(VehicleRental.odometer_from))
                      .filter(VehicleRental.vehicle_id == vehicle_id).scalar())
        values.append(self.session.query(func.max(VehicleRental.odometer_to))
                      .filter(VehicleRental.vehicle_id == vehicle_id).scalar())
        values = [v for v in values if v is not None]
        # u nově koupeného vozidla bez záznamů aspoň stav při nákupu, u prodaného stav při prodeji
        vehicle = self.session.get(Vehicle, vehicle_id)
        if vehicle is not None:
            values += [vehicle.purchase_odometer, vehicle.sale_odometer]
        values = [v for v in values if v is not None]
        return max(values) if values else None

    def last_record_dates(self, vehicles):
        """Datum posledního záznamu u každého vozidla: {vehicle_id: date | None}.

        Bere tankování, servis, výdaje, poznámky, přezutí, kontroly dezénu, půjčení / vrácení
        a nákup / prodej vozidla (jen do dneška - budoucí termíny se nepočítají).
        """
        from datetime import datetime
        from models import TireSwap, TireTreadCheck, VehicleRental
        ids = [v.id for v in vehicles]
        result = {vid: None for vid in ids}
        if not ids:
            return result
        today = date.today()

        def add(vid, value):
            if value is None:
                return
            if isinstance(value, datetime):
                value = value.date()
            if value <= today and (result[vid] is None or value > result[vid]):
                result[vid] = value

        q = self.session.query
        end_of_day = datetime.combine(today, datetime.max.time())
        for model, column, limit in ((FuelRecord, FuelRecord.refuel_datetime, end_of_day),
                                     (VehicleNote, VehicleNote.note_datetime, end_of_day),
                                     (ServiceRecord, ServiceRecord.service_date, today),
                                     (Expense, Expense.expense_date, today),
                                     (TireSwap, TireSwap.swap_date, today),
                                     (TireTreadCheck, TireTreadCheck.check_date, today)):
            rows = (q(model.vehicle_id, func.max(column))
                    .filter(model.vehicle_id.in_(ids), column <= limit).group_by(model.vehicle_id))
            for vid, value in rows:
                add(vid, value)
        for vid, d_from, d_to in q(VehicleRental.vehicle_id, VehicleRental.date_from, VehicleRental.date_to) \
                .filter(VehicleRental.vehicle_id.in_(ids)):
            add(vid, d_from)
            add(vid, d_to)
        for v in vehicles:
            add(v.id, v.purchase_date)
            add(v.id, v.sale_date)
        return result

    def vignette_status(self, vehicles, soon_days=7):
        """Dálniční známka každého vozidla: {vehicle_id: (stav, datum)} podle výdajů s platností.

        Stav: "valid" (platí dnes, datum = konec platnosti), "expiring" (platí, ale končí do soon_days dní),
        "future" (koupená dopředu, datum = začátek platnosti), "expired" (datum = konec poslední).
        Vozidla bez známky ve výsledku nejsou.
        """
        from models.maintenance import VIGNETTE_CATEGORY
        ids = [v.id for v in vehicles]
        if not ids:
            return {}
        today = date.today()
        rows = list(self.session.query(Expense.vehicle_id, Expense.valid_from, Expense.valid_until)
                .filter(Expense.vehicle_id.in_(ids), Expense.category == VIGNETTE_CATEGORY,
                        Expense.valid_until.isnot(None)))
        current, upcoming, past = {}, {}, {}
        for vid, valid_from, valid_until in rows:
            starts = valid_from or valid_until
            if starts <= today <= valid_until:
                current[vid] = max(current.get(vid, valid_until), valid_until)
            elif starts > today:
                upcoming[vid] = min(upcoming.get(vid, starts), starts)
            else:
                past[vid] = max(past.get(vid, valid_until), valid_until)
        result = {}
        for vid in ids:
            if vid in current:
                until = current[vid]
                # navazující známka koupená dopředu prodlužuje platnost
                if vid in upcoming and upcoming[vid] <= until + timedelta(days=1):
                    until = max(u for v, f, u in rows if v == vid and (f or u) > today)
                result[vid] = ("expiring" if (until - today).days < soon_days else "valid", until)
            elif vid in upcoming:
                result[vid] = ("future", upcoming[vid])
            elif vid in past:
                result[vid] = ("expired", past[vid])
        return result

    def get_orphan_vehicles(self):
        return self.session.query(Vehicle).filter(Vehicle.owner_id.is_(None)).all()
