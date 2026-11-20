"""Seznam paliv, který si uživatel spravuje sám (nabízí se ve formuláři tankování)."""
from sqlalchemy import func

from models import FuelRecord, FuelType
from models.fuel_record import FUEL_CATEGORIES, FUEL_TYPES, guess_fuel_category
from models.vehicle import ROLE_EDITOR
from services.errors import NotFoundError, ValidationError
from services.fuel_record_service import FuelRecordService
from services.vehicle_service import VehicleService

MAX_NAME = 30


def _key(name):
    return (name or "").strip().lower()


class FuelTypeService:
    def __init__(self, session):
        self.session = session

    def list_for_user(self, user):
        """Paliva uživatele seřazená podle druhu a názvu. Při prvním použití se seznam založí
        z výchozích paliv a paliv, která už uživatel u svých vozidel zapsal."""
        items = self.session.query(FuelType).filter(FuelType.user_id == user.id).all()
        if not items:
            items = self._seed(user)
        order = {c: i for i, c in enumerate(FUEL_CATEGORIES)}
        return sorted(items, key=lambda t: (order.get(t.category, len(order)), _key(t.name)))

    def names(self, user):
        return [t.name for t in self.list_for_user(user)]

    def _seed(self, user):
        names = {_key(n): (n, n) for n in FUEL_TYPES}
        ids = VehicleService(self.session).get_accessible_ids(user)
        for name in FuelRecordService(self.session).get_used_values(ids, "fuel_type"):
            names.setdefault(_key(name), (name.strip()[:MAX_NAME], guess_fuel_category(name)))
        items = [FuelType(user_id=user.id, name=name, category=category) for name, category in names.values()]
        self.session.add_all(items)
        self.session.commit()
        return items

    def _find(self, user, name):
        return (self.session.query(FuelType)
                .filter(FuelType.user_id == user.id, func.lower(FuelType.name) == _key(name))
                .first())

    def get(self, user, fuel_type_id):
        item = self.session.get(FuelType, fuel_type_id)
        if item is None or item.user_id != user.id:
            raise NotFoundError("Palivo nenalezeno.")
        return item

    @staticmethod
    def _clean(name, category):
        name = " ".join((name or "").split())
        if not name:
            raise ValidationError("Název paliva je povinný.")
        if len(name) > MAX_NAME:
            raise ValidationError(f"Název paliva může mít nejvýše {MAX_NAME} znaků.")
        category = (category or "").strip() or None
        if category is not None and category not in FUEL_CATEGORIES:
            raise ValidationError("Neplatný druh paliva.")
        return name, category

    def resolve(self, user, name):
        """Palivo zadané ve formuláři tankování -> (název, druh).

        Známé palivo vrátí v uloženém tvaru, nové přidá do seznamu (bez commitu - uloží se
        spolu s tankováním) s odhadnutým druhem.
        """
        name = " ".join((name or "").split())
        if not name:
            return name, None
        self.list_for_user(user)  # založí výchozí seznam
        item = self._find(user, name)
        if item is None:
            if len(name) > MAX_NAME:
                return name, None  # chybu ohlásí validace tankování
            item = FuelType(user_id=user.id, name=name, category=guess_fuel_category(name))
            self.session.add(item)
        return item.name, item.category or ""  # "" = palivo bez druhu (neodhadovat)

    def create(self, user, name, category):
        name, category = self._clean(name, category)
        self.list_for_user(user)
        if self._find(user, name):
            raise ValidationError(f"Palivo „{name}“ už v seznamu je.")
        item = FuelType(user_id=user.id, name=name, category=category)
        self.session.add(item)
        self.session.commit()
        return item

    def update(self, user, item, name, category):
        """Přejmenuje palivo / změní druh - i u tankování vozidel, která uživatel smí upravovat."""
        name, category = self._clean(name, category)
        other = self._find(user, name)
        if other is not None and other.id != item.id:
            raise ValidationError(f"Palivo „{name}“ už v seznamu je.")
        old_name = item.name
        item.name, item.category = name, category

        ids = VehicleService(self.session).get_accessible_ids(user, ROLE_EDITOR)
        records = (self.session.query(FuelRecord)
                   .filter(FuelRecord.vehicle_id.in_(ids), FuelRecord.fuel_type == old_name).all()) if ids else []
        for record in records:
            record.fuel_type, record.fuel_category = name, category
        self.session.flush()
        fuel_service = FuelRecordService(self.session)
        for vehicle_id in {r.vehicle_id for r in records}:
            fuel_service.recalculate_consumption(vehicle_id)
        self.session.commit()
        return len(records)

    def delete(self, user, item):
        """Odebere palivo z nabídky (zapsaná tankování zůstanou beze změny)."""
        self.session.delete(item)
        self.session.commit()
