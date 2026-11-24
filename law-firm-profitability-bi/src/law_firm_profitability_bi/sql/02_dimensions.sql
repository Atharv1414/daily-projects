-- Conformed dimensions.
CREATE OR REPLACE TABLE dim_month AS
SELECT
    m::DATE AS month_start,
    last_day(m::DATE) AS month_end,
    year(m) AS calendar_year,
    -- Financial year runs November to October and is named after its closing year.
    year(m + INTERVAL 2 MONTH) AS financial_year,
    (month(m) + 1) % 12 + 1 AS financial_period
FROM generate_series(DATE '2024-11-01', DATE '2026-10-01', INTERVAL 1 MONTH) AS s (m);

CREATE OR REPLACE TABLE dim_org AS SELECT * FROM raw.org;

-- Closure table over a ragged hierarchy: every unit paired with each of its ancestors and
-- itself. Any level can then be filtered with one equality join, whatever its depth.
CREATE OR REPLACE TABLE bridge_org AS
WITH RECURSIVE closure AS (
    SELECT unit_id AS ancestor_id, unit_id AS descendant_id, 0 AS distance
    FROM dim_org
    UNION ALL
    SELECT c.ancestor_id, o.unit_id, c.distance + 1
    FROM closure AS c
    INNER JOIN dim_org AS o ON o.parent_id = c.descendant_id
)
SELECT * FROM closure;

CREATE OR REPLACE TABLE dim_client AS SELECT * FROM raw.clients;

CREATE OR REPLACE TABLE dim_matter AS
SELECT
    m.matter_id,
    m.client_id,
    m.unit_id,
    m.opened_date::DATE AS opened_date,
    m.closed_date::DATE AS closed_date,
    m.discount_pct::DECIMAL(5, 3) AS discount_pct,
    EXISTS (SELECT 1 FROM raw.walls AS w WHERE w.matter_id = m.matter_id) AS is_walled
FROM raw.matters AS m;

CREATE OR REPLACE TABLE dim_wall AS SELECT * FROM raw.walls;

-- SCD Type 2: one row per timekeeper per rate-card period, with grade at the time.
CREATE OR REPLACE TABLE dim_timekeeper AS
SELECT
    row_number() OVER (ORDER BY r.timekeeper_id, r.effective_from) AS timekeeper_key,
    r.timekeeper_id,
    t.name,
    t.office,
    t.unit_id,
    r.grade,
    r.standard_rate::DECIMAL(8, 2) AS standard_rate,
    r.cost_rate::DECIMAL(8, 2) AS cost_rate,
    r.effective_from::DATE AS valid_from,
    coalesce(
        lead(r.effective_from::DATE) OVER (
            PARTITION BY r.timekeeper_id ORDER BY r.effective_from
        ),
        DATE '9999-12-31'
    ) AS valid_to
FROM raw.rates AS r
INNER JOIN raw.timekeepers AS t USING (timekeeper_id);
