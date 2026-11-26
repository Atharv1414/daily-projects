-- Monthly depot scorecard with month-on-month change (LAG) and a league position (RANK).
CREATE OR REPLACE VIEW v_depot_scorecard AS
WITH monthly AS (
    SELECT
        month_start,
        month_name,
        depot_code,
        depot_name,
        SUM(parcels)                                         AS parcels,
        SUM(first_attempt_successes) / SUM(parcels)          AS first_attempt_rate,
        SUM(on_time_parcels) / SUM(parcels)                  AS on_time_rate,
        SUM(returned) / SUM(parcels)                         AS return_rate,
        SUM(total_cost) / SUM(delivered)                     AS cost_per_parcel,
        SUM(parcels) / SUM(driver_hours)                     AS parcels_per_hour,
        SUM(planned_stops) / SUM(capacity)                   AS vehicle_utilisation,
        SUM(co2_kg) / SUM(parcels)                           AS co2_kg_per_parcel
    FROM v_kpi_depot_day
    GROUP BY ALL
)
SELECT
    *,
    on_time_rate - LAG(on_time_rate) OVER w                  AS on_time_rate_mom,
    cost_per_parcel - LAG(cost_per_parcel) OVER w            AS cost_per_parcel_mom,
    RANK() OVER (PARTITION BY month_start ORDER BY on_time_rate DESC)  AS on_time_rank,
    parcels / SUM(parcels) OVER (PARTITION BY month_start)   AS share_of_network
FROM monthly
WINDOW w AS (PARTITION BY depot_code ORDER BY month_start);
