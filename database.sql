CREATE TABLE IF NOT EXISTS `vehicles` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT 'Unique vehicle record identifier',
  `brand` VARCHAR(50) NOT NULL COMMENT 'Vehicle manufacturer brand',
  `model` VARCHAR(50) NOT NULL COMMENT 'Vehicle model name',
  `production_year` YEAR DEFAULT NULL COMMENT 'Year of vehicle production',
  `color` VARCHAR(30) DEFAULT NULL COMMENT 'Vehicle color',
  `license_plate` VARCHAR(10) DEFAULT NULL COMMENT 'Vehicle registration plate number',
  `vin` CHAR(17) DEFAULT NULL COMMENT 'Vehicle Identification Number',
  `note` TEXT COMMENT 'Additional notes about the vehicle',
  `purchase_date` DATE DEFAULT NULL COMMENT 'Date when the vehicle was purchased',
  `sale_date` DATE DEFAULT NULL COMMENT 'Date when the vehicle was sold',
  `is_active` TINYINT(1) NOT NULL DEFAULT 1 COMMENT 'Indicates whether the vehicle is currently active in the fleet',
  `color_hex` CHAR(7) NOT NULL DEFAULT '#FFFFFF' COMMENT 'Vehicle color in HEX format',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_vehicles_license_plate` (`license_plate`),
  UNIQUE KEY `uq_vehicles_vin` (`vin`),
  CHECK (`color_hex` REGEXP '^#[0-9A-Fa-f]{6}$')
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `fuel_records` (
  `id` INT NOT NULL AUTO_INCREMENT COMMENT 'Unique fuel record identifier',
  `vehicle_id` INT NOT NULL COMMENT 'Reference to the vehicle',
  `refuel_datetime` DATETIME NOT NULL COMMENT 'Date and time of refueling',
  `odometer` INT NOT NULL COMMENT 'Vehicle odometer reading in kilometers at the time of refueling',
  `fuel_type` VARCHAR(15) NOT NULL COMMENT 'Type of fuel (petrol, diesel, LPG, CNG, electricity)',
  `volume_liters` DECIMAL(7,2) NOT NULL COMMENT 'Amount of fuel filled in liters',
  `unit_price` DECIMAL(10,3) DEFAULT NULL COMMENT 'Price per liter in the original payment currency',
  `price_paid` DECIMAL(12,3) NOT NULL COMMENT 'Total amount paid in the original payment currency',
  `currency_code` CHAR(3) NOT NULL DEFAULT 'CZK' COMMENT 'Currency code of the payment (CZK, EUR, PLN etc.)',
  `unit_price_local` DECIMAL(10,3) DEFAULT NULL COMMENT 'Price per liter in the local currency',
  `price_local` DECIMAL(12,3) DEFAULT NULL COMMENT 'Total price converted to local currency',
  `payment_method` VARCHAR(20) DEFAULT NULL COMMENT 'Payment method used',
  `station_name` VARCHAR(100) DEFAULT NULL COMMENT 'Name of the fuel station',
  `full_tank` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Indicates the tank was filled completely',
  `skipped_refuel` TINYINT(1) NOT NULL DEFAULT 0 COMMENT 'Indicates that some refueling events were skipped',
  `consumption` DECIMAL(5,2) DEFAULT NULL COMMENT 'Calculated fuel consumption in liters per 100 km',
  `note` TEXT COMMENT 'Additional notes',
  PRIMARY KEY (`id`),
  KEY `idx_fuel_records_vehicle_id` (`vehicle_id`),
  KEY `idx_fuel_records_refuel_date` (`refuel_date`),
  CONSTRAINT `fk_fuel_records_vehicle`
    FOREIGN KEY (`vehicle_id`) REFERENCES `vehicles` (`id`)
    ON DELETE CASCADE
    ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;