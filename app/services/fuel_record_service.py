from models import FuelRecord, Vehicle

class FuelRecordService:
    def __init__(self, session):
        self.session = session

    def get_all_fuel_records(self):
        return self.session.query(FuelRecord).all()

    def get_fuel_records_for_vehicle(self, vehicle_id):
        return (
            self.session.query(FuelRecord)
            .filter(FuelRecord.vehicle_id == vehicle_id)
            .order_by(FuelRecord.refuel_date.desc(), FuelRecord.refuel_time.desc())
            .all()
        )