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
            .order_by(FuelRecord.refuel_datetime.desc())
            .all()
        )
    
    def create_fuel_record(self, vehicle_id, refuel_datetime, odometer, fuel_type, volume_liters, unit_price, price_paid, currency_code, unit_price_local, price_local, payment_method=None, station_name=None, full_tank=False, skipped_refuel=False, consumption=None, note=None):
        if not vehicle_id or not refuel_datetime or not odometer or not fuel_type or volume_liters is None or price_paid is None or not currency_code:
            raise ValueError("Některé povinné údaje chybí.")

        fuel_record = FuelRecord(
            vehicle_id=vehicle_id,
            refuel_datetime=refuel_datetime,
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

        self.session.add(fuel_record)
        self.session.commit()

        return fuel_record