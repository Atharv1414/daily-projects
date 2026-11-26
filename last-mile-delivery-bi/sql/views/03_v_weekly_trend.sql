-- Weekly trend per depot plus a network total row (depot_code = 'ALL') via GROUPING SETS.
CREATE OR REPLACE VIEW v_weekly_trend AS
SELECT
    week_start,
    COALESCE(depot_code, 'ALL')                          AS depot_code,
    SUM(parcels)                                         AS parcels,
    SUM(first_attempt_successes) / SUM(parcels)          AS first_attempt_rate,
    SUM(on_time_parcels) / SUM(parcels)                  AS on_time_rate,
    SUM(total_cost) / SUM(delivered)                     AS cost_per_parcel,
    SUM(planned_stops) / SUM(capacity)                   AS vehicle_utilisation
FROM v_kpi_depot_day
GROUP BY GROUPING SETS ((week_start, depot_code), (week_start));
