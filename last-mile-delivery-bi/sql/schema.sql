-- Star schema for last-mile delivery operations.
-- Two fact tables at different grains share conformed dimensions:
--   fact_delivery   one row per parcel            (service quality measures)
--   fact_route_day  one row per route per day     (cost, capacity and emissions measures)

CREATE TABLE dim_date (
    date_key     INTEGER PRIMARY KEY,   -- YYYYMMDD
    full_date    DATE NOT NULL,
    year         SMALLINT NOT NULL,
    quarter      SMALLINT NOT NULL,
    month        SMALLINT NOT NULL,
    month_name   VARCHAR NOT NULL,
    month_start  DATE NOT NULL,
    iso_week     SMALLINT NOT NULL,
    week_start   DATE NOT NULL,         -- Monday of the ISO week
    day_of_week  SMALLINT NOT NULL,     -- 1 = Monday
    day_name     VARCHAR NOT NULL,
    is_weekend   BOOLEAN NOT NULL,
    is_peak      BOOLEAN NOT NULL       -- November onwards (Black Friday build-up)
);

CREATE TABLE dim_depot (
    depot_key   INTEGER PRIMARY KEY,
    depot_code  VARCHAR NOT NULL UNIQUE,
    depot_name  VARCHAR NOT NULL,
    region      VARCHAR NOT NULL
);

CREATE TABLE dim_route (
    route_key   INTEGER PRIMARY KEY,
    route_code  VARCHAR NOT NULL UNIQUE,
    depot_key   INTEGER NOT NULL REFERENCES dim_depot (depot_key),
    area_type   VARCHAR NOT NULL CHECK (area_type IN ('Urban', 'Suburban', 'Rural'))
);

CREATE TABLE dim_driver (
    driver_key       INTEGER PRIMARY KEY,
    driver_code      VARCHAR NOT NULL UNIQUE,
    depot_key        INTEGER NOT NULL REFERENCES dim_depot (depot_key),
    employment_type  VARCHAR NOT NULL CHECK (employment_type IN ('Employed', 'Agency')),
    tenure_months    INTEGER NOT NULL
);

CREATE TABLE dim_vehicle (
    vehicle_key       INTEGER PRIMARY KEY,
    registration      VARCHAR NOT NULL UNIQUE,
    depot_key         INTEGER NOT NULL REFERENCES dim_depot (depot_key),
    vehicle_type      VARCHAR NOT NULL,
    fuel_type         VARCHAR NOT NULL CHECK (fuel_type IN ('Diesel', 'Electric')),
    capacity_parcels  INTEGER NOT NULL CHECK (capacity_parcels > 0)
);

CREATE TABLE dim_service (
    service_key          INTEGER PRIMARY KEY,
    service_level        VARCHAR NOT NULL UNIQUE,
    promise_description  VARCHAR NOT NULL
);

CREATE TABLE fact_route_day (
    route_day_id      INTEGER PRIMARY KEY,
    date_key          INTEGER NOT NULL REFERENCES dim_date (date_key),
    depot_key         INTEGER NOT NULL REFERENCES dim_depot (depot_key),
    route_key         INTEGER NOT NULL REFERENCES dim_route (route_key),
    driver_key        INTEGER NOT NULL REFERENCES dim_driver (driver_key),
    vehicle_key       INTEGER NOT NULL REFERENCES dim_vehicle (vehicle_key),
    planned_stops     INTEGER NOT NULL CHECK (planned_stops > 0),
    vehicle_capacity  INTEGER NOT NULL,
    km_driven         DECIMAL(8, 1) NOT NULL,
    driver_hours      DECIMAL(6, 2) NOT NULL,
    labour_cost       DECIMAL(10, 2) NOT NULL,
    vehicle_cost      DECIMAL(10, 2) NOT NULL,
    total_cost        DECIMAL(10, 2) NOT NULL,
    co2_kg            DECIMAL(10, 2) NOT NULL
);

CREATE TABLE fact_delivery (
    parcel_id              VARCHAR PRIMARY KEY,
    date_key               INTEGER NOT NULL REFERENCES dim_date (date_key),
    route_day_id           INTEGER NOT NULL REFERENCES fact_route_day (route_day_id),
    depot_key              INTEGER NOT NULL REFERENCES dim_depot (depot_key),
    route_key              INTEGER NOT NULL REFERENCES dim_route (route_key),
    driver_key             INTEGER NOT NULL REFERENCES dim_driver (driver_key),
    vehicle_key            INTEGER NOT NULL REFERENCES dim_vehicle (vehicle_key),
    service_key            INTEGER NOT NULL REFERENCES dim_service (service_key),
    attempts               SMALLINT NOT NULL CHECK (attempts BETWEEN 1 AND 3),
    first_attempt_success  BOOLEAN NOT NULL,
    delivered              BOOLEAN NOT NULL,
    on_time                BOOLEAN NOT NULL,
    failure_reason         VARCHAR,          -- NULL when the first attempt succeeded
    redelivery_cost        DECIMAL(8, 2) NOT NULL
);
