-- Diesel versus electric vans: cost and emissions per parcel by depot.
CREATE OR REPLACE VIEW v_fleet_mix AS
SELECT
    dp.depot_code,
    v.fuel_type,
    COUNT(*)                                 AS route_days,
    SUM(r.planned_stops)                     AS parcels,
    SUM(r.vehicle_cost) / SUM(r.planned_stops) AS vehicle_cost_per_parcel,
    SUM(r.co2_kg) / SUM(r.planned_stops)     AS co2_kg_per_parcel
FROM fact_route_day AS r
JOIN dim_vehicle AS v USING (vehicle_key)
JOIN dim_depot AS dp ON dp.depot_key = r.depot_key
GROUP BY dp.depot_code, v.fuel_type;
