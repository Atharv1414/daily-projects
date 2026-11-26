"""Seeded synthetic data for a UK last-mile parcel carrier.

The generator produces a small star schema as pandas DataFrames: six dimension
tables and two fact tables at different grains (one row per parcel, and one row
per route per operating day). Business effects are built in on purpose so the
dashboard has something real to find: a weaker depot, agency-driver and rural
penalties, a November peak that overloads vans, and cheaper electric vans.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# code, name, region, volume multiplier, first-attempt effect (logit), EV share
DEPOTS: list[tuple[str, str, str, float, float, float]] = [
    ("LDN", "London East", "London", 1.12, 0.00, 0.55),
    ("MAN", "Manchester Trafford", "North West", 1.00, 0.05, 0.20),
    ("BHM", "Birmingham Hams Hall", "West Midlands", 1.06, -0.55, 0.20),
    ("LDS", "Leeds Stourton", "Yorkshire", 0.95, 0.12, 0.20),
    ("BRS", "Bristol Avonmouth", "South West", 0.90, 0.02, 0.50),
    ("GLA", "Glasgow Eurocentral", "Scotland", 0.86, -0.12, 0.15),
]

# vehicle type -> (fuel, parcel capacity, cost per km £, fixed daily cost £, kg CO2e per km)
VEHICLE_TYPES: dict[str, tuple[str, int, float, float, float]] = {
    "Diesel LWB": ("Diesel", 150, 0.24, 24.0, 0.29),
    "Diesel SWB": ("Diesel", 128, 0.19, 21.0, 0.23),
    "Electric eVan": ("Electric", 122, 0.05, 26.0, 0.05),
}

# area type -> (share of routes, base km, stops multiplier, first-attempt effect)
AREA_TYPES: dict[str, tuple[float, float, float, float]] = {
    "Urban": (0.45, 42.0, 1.08, 0.05),
    "Suburban": (0.35, 68.0, 1.00, 0.00),
    "Rural": (0.20, 118.0, 0.74, -0.30),
}

SERVICES: list[tuple[str, str, float]] = [
    ("Next Day", "Delivered by 18:00 the day after collection", 0.68),
    ("Same Day", "Delivered by 21:00 on the day of order", 0.10),
    ("Standard", "Delivered within 2-3 working days", 0.22),
]

FAILURE_REASONS: list[tuple[str, float]] = [
    ("Customer not in", 0.50),
    ("Safe place unavailable", 0.18),
    ("Access / gated property", 0.14),
    ("Address not found", 0.12),
    ("Damaged in transit", 0.06),
]
OUT_OF_TIME = "Out of time on route"

HOURLY_RATE = {"Employed": 14.80, "Agency": 19.60}  # fully loaded £/hour
REDELIVERY_COST = 3.40  # £ per extra attempt
RETURN_COST = 5.80  # £ per parcel returned to sender

SEASONALITY = {6: 0.93, 7: 0.90, 8: 0.88, 9: 0.97, 10: 1.03, 11: 1.20, 12: 1.30}
DOW_VOLUME = {0: 1.14, 1: 1.05, 2: 1.00, 3: 1.00, 4: 1.02, 5: 0.72}  # Mon..Sat
DOW_EFFECT = {0: -0.12, 1: 0.0, 2: 0.0, 3: 0.0, 4: -0.05, 5: 0.22}  # first-attempt logit


@dataclass(frozen=True)
class GeneratorConfig:
    """Parameters for one synthetic run. The same config always yields the same data."""

    start: str = "2026-06-01"
    end: str = "2026-11-21"
    routes_per_depot: int = 6
    base_stops: float = 98.0
    seed: int = 42


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def build_dim_date(start: str, end: str) -> pd.DataFrame:
    """Calendar dimension with an integer YYYYMMDD key."""
    dates = pd.date_range(start, end, freq="D")
    iso = dates.isocalendar()
    return pd.DataFrame(
        {
            "date_key": dates.strftime("%Y%m%d").astype(int),
            "full_date": dates.date,
            "year": dates.year,
            "quarter": dates.quarter,
            "month": dates.month,
            "month_name": dates.strftime("%b %Y"),
            "month_start": dates.to_period("M").start_time.date,
            "iso_week": iso.week.to_numpy(),
            "week_start": (dates - pd.to_timedelta(dates.day_of_week, unit="D")).date,
            "day_of_week": dates.day_of_week + 1,
            "day_name": dates.strftime("%a"),
            "is_weekend": dates.day_of_week >= 5,
            "is_peak": dates.month >= 11,
        }
    )


def generate(config: GeneratorConfig | None = None) -> dict[str, pd.DataFrame]:
    """Generate every table of the star schema, keyed by table name."""
    cfg = config or GeneratorConfig()
    rng = np.random.default_rng(cfg.seed)

    dim_date = build_dim_date(cfg.start, cfg.end)
    dim_depot = pd.DataFrame(
        {
            "depot_key": range(1, len(DEPOTS) + 1),
            "depot_code": [d[0] for d in DEPOTS],
            "depot_name": [d[1] for d in DEPOTS],
            "region": [d[2] for d in DEPOTS],
        }
    )
    dim_service = pd.DataFrame(
        {
            "service_key": range(1, len(SERVICES) + 1),
            "service_level": [s[0] for s in SERVICES],
            "promise_description": [s[1] for s in SERVICES],
        }
    )

    routes, drivers, vehicles = [], [], []
    for depot_key, (code, _name, _region, _vol, _eff, ev_share) in enumerate(DEPOTS, start=1):
        areas = rng.choice(list(AREA_TYPES), size=cfg.routes_per_depot, p=[a[0] for a in AREA_TYPES.values()])
        for i, area in enumerate(areas, start=1):
            routes.append((f"{code}-R{i:02d}", depot_key, str(area)))
        for i in range(1, cfg.routes_per_depot * 2 + 1):
            agency = rng.random() < 0.30
            tenure = int(rng.gamma(1.5, 3.0)) + 1 if agency else int(rng.gamma(2.2, 14.0)) + 3
            drivers.append((f"{code}-D{i:03d}", depot_key, "Agency" if agency else "Employed", tenure))
        for i in range(1, cfg.routes_per_depot + 3):
            if rng.random() < ev_share:
                vtype = "Electric eVan"
            else:
                vtype = str(rng.choice(["Diesel LWB", "Diesel SWB"], p=[0.6, 0.4]))
            vehicles.append((f"{code}{i:02d} {rng.integers(100, 999)}", depot_key, vtype))

    dim_route = pd.DataFrame(routes, columns=["route_code", "depot_key", "area_type"])
    dim_route.insert(0, "route_key", range(1, len(dim_route) + 1))
    dim_driver = pd.DataFrame(
        drivers, columns=["driver_code", "depot_key", "employment_type", "tenure_months"]
    )
    dim_driver.insert(0, "driver_key", range(1, len(dim_driver) + 1))
    dim_vehicle = pd.DataFrame(vehicles, columns=["registration", "depot_key", "vehicle_type"])
    dim_vehicle.insert(0, "vehicle_key", range(1, len(dim_vehicle) + 1))
    dim_vehicle["fuel_type"] = dim_vehicle["vehicle_type"].map(lambda t: VEHICLE_TYPES[t][0])
    dim_vehicle["capacity_parcels"] = dim_vehicle["vehicle_type"].map(lambda t: VEHICLE_TYPES[t][1])

    fact_route_day = _route_days(rng, cfg, dim_date, dim_route, dim_driver, dim_vehicle)
    fact_delivery = _deliveries(rng, fact_route_day, dim_route, dim_driver)

    return {
        "dim_date": dim_date,
        "dim_depot": dim_depot,
        "dim_route": dim_route,
        "dim_driver": dim_driver,
        "dim_vehicle": dim_vehicle,
        "dim_service": dim_service,
        "fact_route_day": fact_route_day,
        "fact_delivery": fact_delivery,
    }


def _route_days(
    rng: np.random.Generator,
    cfg: GeneratorConfig,
    dim_date: pd.DataFrame,
    dim_route: pd.DataFrame,
    dim_driver: pd.DataFrame,
    dim_vehicle: pd.DataFrame,
) -> pd.DataFrame:
    """One row per route per operating day (Monday to Saturday)."""
    operating = dim_date[dim_date["day_of_week"] <= 6]
    grid = operating[["date_key", "month", "day_of_week"]].merge(dim_route, how="cross")
    n = len(grid)

    depot_vol = grid["depot_key"].map({i: d[3] for i, d in enumerate(DEPOTS, start=1)})
    area = grid["area_type"].map(AREA_TYPES)
    lam = (
        cfg.base_stops
        * depot_vol
        * area.map(lambda a: a[2])
        * grid["month"].map(SEASONALITY)
        * (grid["day_of_week"] - 1).map(DOW_VOLUME)
    )

    # Each route has a home van; on 10% of days a spare van from the same depot is used.
    vans_by_depot = dim_vehicle.groupby("depot_key")["vehicle_key"].apply(list).to_dict()
    home_van = {
        r.route_key: vans_by_depot[r.depot_key][i % len(vans_by_depot[r.depot_key])]
        for i, r in enumerate(dim_route.itertuples())
    }
    drivers_by_depot = dim_driver.groupby("depot_key")["driver_key"].apply(list).to_dict()

    vehicle_key = np.empty(n, dtype=int)
    driver_key = np.empty(n, dtype=int)
    for i, (route_key, depot_key) in enumerate(zip(grid["route_key"], grid["depot_key"], strict=True)):
        vans = vans_by_depot[depot_key]
        vehicle_key[i] = home_van[route_key] if rng.random() > 0.10 else vans[rng.integers(len(vans))]
        pool = drivers_by_depot[depot_key]
        driver_key[i] = pool[rng.integers(len(pool))]

    van = dim_vehicle.set_index("vehicle_key").loc[vehicle_key]
    capacity = van["capacity_parcels"].to_numpy()
    stops = np.minimum(rng.poisson(lam.to_numpy()), np.floor(capacity * 1.10)).astype(int)
    stops = np.maximum(stops, 20)

    base_km = area.map(lambda a: a[1]).to_numpy()
    km = base_km * rng.uniform(0.88, 1.12, n) * (stops / 100.0) ** 0.4
    hours = np.minimum(1.1 + stops * 0.043 + km / 36.0 + rng.normal(0, 0.25, n), 11.5)

    emp = dim_driver.set_index("driver_key").loc[driver_key, "employment_type"].to_numpy()
    labour = hours * np.where(emp == "Agency", HOURLY_RATE["Agency"], HOURLY_RATE["Employed"])
    vtypes = van["vehicle_type"].to_numpy()
    per_km = np.array([VEHICLE_TYPES[t][2] for t in vtypes])
    fixed = np.array([VEHICLE_TYPES[t][3] for t in vtypes])
    co2_per_km = np.array([VEHICLE_TYPES[t][4] for t in vtypes])

    return pd.DataFrame(
        {
            "route_day_id": np.arange(1, n + 1),
            "date_key": grid["date_key"].to_numpy(),
            "depot_key": grid["depot_key"].to_numpy(),
            "route_key": grid["route_key"].to_numpy(),
            "driver_key": driver_key,
            "vehicle_key": vehicle_key,
            "planned_stops": stops,
            "vehicle_capacity": capacity,
            "km_driven": km.round(1),
            "driver_hours": hours.round(2),
            "labour_cost": labour.round(2),
            "vehicle_cost": (km * per_km + fixed).round(2),
            "total_cost": (labour + km * per_km + fixed).round(2),
            "co2_kg": (km * co2_per_km).round(2),
        }
    )


def _deliveries(
    rng: np.random.Generator,
    route_day: pd.DataFrame,
    dim_route: pd.DataFrame,
    dim_driver: pd.DataFrame,
) -> pd.DataFrame:
    """One row per parcel, expanded from the planned stops of each route day."""
    idx = np.repeat(np.arange(len(route_day)), route_day["planned_stops"].to_numpy())
    rd = route_day.iloc[idx].reset_index(drop=True)
    n = len(rd)

    date = pd.to_datetime(rd["date_key"].astype(str), format="%Y%m%d")
    month = date.dt.month.to_numpy()
    dow = date.dt.day_of_week.to_numpy()
    util = (rd["planned_stops"] / rd["vehicle_capacity"]).to_numpy()
    service_key = rng.choice([1, 2, 3], size=n, p=[s[2] for s in SERVICES])

    depot_eff = rd["depot_key"].map({i: d[4] for i, d in enumerate(DEPOTS, start=1)}).to_numpy()
    area_eff = rd["route_key"].map(
        dim_route.set_index("route_key")["area_type"].map(lambda a: AREA_TYPES[a][3])
    )
    drv = dim_driver.set_index("driver_key").loc[rd["driver_key"]]
    agency = (drv["employment_type"] == "Agency").to_numpy()
    tenure = drv["tenure_months"].to_numpy()

    overload = np.maximum(util - 0.90, 0.0)
    logit_fa = (
        2.45
        + depot_eff
        + area_eff.to_numpy()
        - 0.38 * agency
        + 0.30 * np.minimum(tenure, 24) / 24
        - 6.0 * overload
        - 0.15 * (month >= 11)
        + np.vectorize(DOW_EFFECT.get)(dow)
        - 0.20 * (service_key == 2)
    )
    first_ok = rng.random(n) < _sigmoid(logit_fa)

    # Later attempts: 2nd succeeds 72% of the time, 3rd 55%; otherwise returned to sender.
    second_ok = rng.random(n) < 0.72
    third_ok = rng.random(n) < 0.55
    attempts = np.where(first_ok, 1, np.where(second_ok, 2, 3))
    delivered = first_ok | second_ok | third_ok

    reasons = rng.choice([r[0] for r in FAILURE_REASONS], size=n, p=[r[1] for r in FAILURE_REASONS])
    out_of_time = rng.random(n) < np.clip(overload * 6.0 + 0.03, 0, 0.85)
    failure_reason = np.where(first_ok, None, np.where(out_of_time, OUT_OF_TIME, reasons))

    logit_ot = 2.9 + 0.6 * depot_eff - 4.0 * np.maximum(util - 0.85, 0.0) - 0.7 * (service_key == 2)
    logit_ot = logit_ot - 0.30 * (month >= 11)
    on_time = first_ok & (rng.random(n) < _sigmoid(logit_ot))

    redelivery = (attempts - 1) * REDELIVERY_COST + np.where(delivered, 0.0, RETURN_COST)

    return pd.DataFrame(
        {
            "parcel_id": [f"PCL{i:08d}" for i in range(1, n + 1)],
            "date_key": rd["date_key"].to_numpy(),
            "route_day_id": rd["route_day_id"].to_numpy(),
            "depot_key": rd["depot_key"].to_numpy(),
            "route_key": rd["route_key"].to_numpy(),
            "driver_key": rd["driver_key"].to_numpy(),
            "vehicle_key": rd["vehicle_key"].to_numpy(),
            "service_key": service_key,
            "attempts": attempts,
            "first_attempt_success": first_ok,
            "delivered": delivered,
            "on_time": on_time,
            "failure_reason": failure_reason,
            "redelivery_cost": redelivery.round(2),
        }
    )
