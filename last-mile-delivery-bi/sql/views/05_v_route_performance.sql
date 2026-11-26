-- Route-level drill-down: service and cost measures for each route over the whole period.
CREATE OR REPLACE VIEW v_route_performance AS
WITH svc AS (
    SELECT
        route_key,
        COUNT(*)                                                AS parcels,
        AVG(CASE WHEN first_attempt_success THEN 1.0 ELSE 0 END) AS first_attempt_rate,
        AVG(CASE WHEN on_time THEN 1.0 ELSE 0 END)              AS on_time_rate,
        SUM(redelivery_cost)                                    AS redelivery_cost,
        COUNT(*) FILTER (WHERE delivered)                       AS delivered
    FROM fact_delivery
    GROUP BY route_key
),
ops AS (
    SELECT
        route_key,
        SUM(total_cost)                          AS route_cost,
        SUM(planned_stops) / SUM(vehicle_capacity) AS vehicle_utilisation,
        AVG(km_driven)                           AS avg_km_per_day,
        SUM(planned_stops) / SUM(driver_hours)   AS parcels_per_hour
    FROM fact_route_day
    GROUP BY route_key
)
SELECT
    dp.depot_code,
    r.route_code,
    r.area_type,
    s.parcels,
    s.first_attempt_rate,
    s.on_time_rate,
    (o.route_cost + s.redelivery_cost) / s.delivered  AS cost_per_parcel,
    o.vehicle_utilisation,
    o.avg_km_per_day,
    o.parcels_per_hour,
    RANK() OVER (PARTITION BY dp.depot_code ORDER BY s.on_time_rate DESC) AS rank_in_depot
FROM svc AS s
JOIN ops AS o USING (route_key)
JOIN dim_route AS r USING (route_key)
JOIN dim_depot AS dp ON dp.depot_key = r.depot_key;
