-- Driver league table: first-attempt quartile within each depot (NTILE) for coaching.
CREATE OR REPLACE VIEW v_driver_league AS
WITH perf AS (
    SELECT
        f.driver_key,
        COUNT(*)                                                    AS parcels,
        AVG(CASE WHEN f.first_attempt_success THEN 1.0 ELSE 0 END)  AS first_attempt_rate,
        AVG(CASE WHEN f.on_time THEN 1.0 ELSE 0 END)                AS on_time_rate
    FROM fact_delivery AS f
    GROUP BY f.driver_key
)
SELECT
    dp.depot_code,
    dr.driver_code,
    dr.employment_type,
    dr.tenure_months,
    p.parcels,
    p.first_attempt_rate,
    p.on_time_rate,
    NTILE(4) OVER (PARTITION BY dp.depot_code ORDER BY p.first_attempt_rate DESC) AS quartile
FROM perf AS p
JOIN dim_driver AS dr USING (driver_key)
JOIN dim_depot AS dp ON dp.depot_key = dr.depot_key;
