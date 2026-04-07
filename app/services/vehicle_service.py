from models import Vehicle


class VehicleService:
    def __init__(self, session):
        self.session = session

    def get_all_vehicles(self):
        return self.session.query(Vehicle).all()

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
    
    def delete_vehicle():
        pass

    def edit_vehicle():
        pass

    def activate_vehicle():
        pass

    def deactivate_vehicle():
        pass