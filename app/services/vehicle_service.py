from models import Vehicle


class VehicleService:
    def __init__(self, session):
        self.session = session

    def get_all_vehicles(self):
        return self.session.query(Vehicle).all()
    
    def get_vehicle(self, vehicle_id):
        return (self.session.query(Vehicle)
        .filter(Vehicle.id == vehicle_id)
        .first())

    def create_vehicle(self, brand, model, license_plate=None, color=None):
        if not brand or not model:
            raise ValueError("Značka a model jsou povinné.")

        vehicle = Vehicle(
            brand=brand,
            model=model,
            license_plate=license_plate,
            color=color
        )

        self.session.add(vehicle)
        self.session.commit()

        return vehicle
    
    def delete_vehicle(self, vehicle_id):
        vehicle = self.session.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        if not vehicle:
            raise ValueError("Vozidlo s daným ID nebylo nalezeno.")
        self.session.delete(vehicle)
        self.session.commit()

    def edit_vehicle(self, vehicle_id, brand=None, model=None, license_plate=None, color=None):
        vehicle = self.get_vehicle(vehicle_id)
        if not vehicle:
            raise ValueError("Vozidlo s daným ID nebylo nalezeno.")

        if brand is not None:
            vehicle.brand = brand
        if model is not None:
            vehicle.model = model
        if license_plate is not None:
            vehicle.license_plate = license_plate
        if color is not None:
            vehicle.color = color

        self.session.commit()
        return vehicle

    def activate_vehicle(self, vehicle_id):
        self.edit_vehicle(vehicle_id, is_active=True)

    def deactivate_vehicle():
        pass