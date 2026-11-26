-- How van fill level affects service: route days bucketed by utilisation.
CREATE OR REPLACE VIEW v_utilisation_bands AS
WITH rd AS (
    SELECT
        r.route_day_id,
        r.planned_stops / r.vehicle_capacity AS utilisation,
        CASE
            WHEN r.planned_stops / r.vehicle_capacity < 0.70 THEN '1. Under 70%'
            WHEN r.planned_stops / r.vehicle_capacity < 0.85 THEN '2. 70-85%'
            WHEN r.planned_stops / r.vehicle_capacity < 0.95 THEN '3. 85-95%'
            ELSE '4. 95% and over'
        END AS utilisation_band
    FROM fact_route_day AS r
)
SELECT
    rd.utilisation_band,
    COUNT(DISTINCT rd.route_day_id)                                  AS route_days,
    COUNT(*)                                                         AS parcels,
    AVG(rd.utilisation)                                              AS avg_utilisation,
    AVG(CASE WHEN f.on_time THEN 1.0 ELSE 0 END)                     AS on_time_rate,
    AVG(CASE WHEN f.first_attempt_success THEN 1.0 ELSE 0 END)       AS first_attempt_rate,
    AVG(CASE WHEN f.failure_reason = 'Out of time on route' THEN 1.0 ELSE 0 END) AS out_of_time_rate
FROM rd
JOIN fact_delivery AS f USING (route_day_id)
GROUP BY rd.utilisation_band;
