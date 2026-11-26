-- Pareto of first-attempt failure reasons, per depot and for the whole network ('ALL').
CREATE OR REPLACE VIEW v_failure_pareto AS
WITH counts AS (
    SELECT
        COALESCE(dp.depot_code, 'ALL')  AS depot_code,
        f.failure_reason,
        COUNT(*)                        AS failures
    FROM fact_delivery AS f
    JOIN dim_depot AS dp USING (depot_key)
    WHERE NOT f.first_attempt_success
    GROUP BY GROUPING SETS ((dp.depot_code, f.failure_reason), (f.failure_reason))
)
SELECT
    depot_code,
    failure_reason,
    failures,
    failures / SUM(failures) OVER (PARTITION BY depot_code)                     AS share,
    SUM(failures) OVER (PARTITION BY depot_code ORDER BY failures DESC, failure_reason
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
        / SUM(failures) OVER (PARTITION BY depot_code)                          AS cumulative_share,
    ROW_NUMBER() OVER (PARTITION BY depot_code ORDER BY failures DESC, failure_reason) AS reason_rank
FROM counts;
