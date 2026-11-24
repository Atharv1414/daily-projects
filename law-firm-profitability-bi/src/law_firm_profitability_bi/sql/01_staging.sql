-- Staging: de-duplicate exports and quarantine rows that cannot be valid.
CREATE OR REPLACE TABLE stg_time AS
WITH ranked AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY entry_id, version ORDER BY posted_at
        ) AS copy_number
    FROM raw.time
)
SELECT
    r.entry_id,
    r.version,
    r.work_date::DATE AS work_date,
    r.posted_at::DATE AS posted_at,
    r.timekeeper_id,
    r.matter_id,
    r.hours::DECIMAL(6, 1) AS hours,
    r.status = 'active' AS is_active,
    CASE
        WHEN t.timekeeper_id IS NULL THEN 'unknown_timekeeper'
        WHEN m.matter_id IS NULL THEN 'unknown_matter'
        WHEN r.hours <= 0 OR r.hours > 24 THEN 'impossible_hours'
        WHEN r.posted_at < r.work_date THEN 'posted_before_worked'
    END AS reject_reason
FROM ranked AS r
LEFT JOIN raw.timekeepers AS t USING (timekeeper_id)
LEFT JOIN raw.matters AS m USING (matter_id)
WHERE r.copy_number = 1;

CREATE OR REPLACE TABLE quarantine_time AS
SELECT * FROM stg_time WHERE reject_reason IS NOT NULL;

CREATE OR REPLACE TABLE load_audit AS
SELECT
    (SELECT count(*) FROM raw.time) AS raw_rows,
    (SELECT count(*) FROM raw.time) - (SELECT count(*) FROM stg_time) AS duplicate_rows,
    (SELECT count(*) FROM quarantine_time) AS quarantined_rows;
