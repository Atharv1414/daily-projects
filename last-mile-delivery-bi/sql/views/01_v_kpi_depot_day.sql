-- Drill-across view: service measures from fact_delivery and cost/capacity measures from
-- fact_route_day are aggregated separately to a shared grain (depot x day) and then joined.
-- Joining the two facts row-to-row would fan out route costs once per parcel.
-- Only additive components are stored here; ratios are computed by the semantic layer
-- (metrics.py) as SUM(numerator) / SUM(denominator), so they roll up correctly.
CREATE OR REPLACE VIEW v_kpi_depot_day AS
WITH parcels AS (
    SELECT
        date_key,
        depot_key,
        COUNT(*)                                           AS parcels,
        COUNT(*) FILTER (WHERE delivered)                  AS delivered,
        COUNT(*) FILTER (WHERE first_attempt_success)      AS first_attempt_successes,
        COUNT(*) FILTER (WHERE on_time)                    AS on_time_parcels,
        COUNT(*) FILTER (WHERE NOT delivered)              AS returned,
        SUM(attempts)                                      AS attempts,
        SUM(redelivery_cost)                               AS redelivery_cost
    FROM fact_delivery
    GROUP BY date_key, depot_key
),
routes AS (
    SELECT
        date_key,
        depot_key,
        COUNT(*)               AS route_days,
        SUM(planned_stops)     AS planned_stops,
        SUM(vehicle_capacity)  AS capacity,
        SUM(driver_hours)      AS driver_hours,
        SUM(km_driven)         AS km_driven,
        SUM(total_cost)        AS route_cost,
        SUM(co2_kg)            AS co2_kg
    FROM fact_route_day
    GROUP BY date_key, depot_key
)
SELECT
    d.date_key,
    d.full_date,
    d.week_start,
    d.month_start,
    d.month_name,
    dp.depot_code,
    dp.depot_name,
    p.parcels,
    p.delivered,
    p.first_attempt_successes,
    p.on_time_parcels,
    p.returned,
    p.attempts,
    r.route_days,
    r.planned_stops,
    r.capacity,
    r.driver_hours,
    r.km_driven,
    r.co2_kg,
    r.route_cost + p.redelivery_cost AS total_cost
FROM parcels AS p
JOIN routes AS r USING (date_key, depot_key)
JOIN dim_date AS d USING (date_key)
JOIN dim_depot AS dp USING (depot_key);
