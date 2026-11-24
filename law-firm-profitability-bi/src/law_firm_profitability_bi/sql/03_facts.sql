-- Bitemporal time fact. work_date is when it happened; [known_from, known_to) is when the
-- firm believed this version. Filtering on the second axis reproduces any past report.
CREATE OR REPLACE TABLE fact_time AS
WITH versions AS (
    SELECT
        *,
        coalesce(
            lead(posted_at) OVER (PARTITION BY entry_id ORDER BY version),
            DATE '9999-12-31'
        ) AS known_to
    FROM stg_time
    WHERE reject_reason IS NULL
)
SELECT
    v.entry_id,
    v.version,
    v.work_date,
    date_trunc('month', v.work_date)::DATE AS work_month,
    v.posted_at AS known_from,
    v.known_to,
    v.is_active,
    v.matter_id,
    m.unit_id,
    t.timekeeper_key,
    t.grade,
    v.hours,
    (v.hours * t.standard_rate)::DECIMAL(14, 2) AS standard_value,
    (v.hours * round(t.standard_rate * (1 - m.discount_pct), 2))::DECIMAL(14, 2) AS net_value,
    (v.hours * t.cost_rate)::DECIMAL(14, 2) AS cost_value
FROM versions AS v
INNER JOIN dim_matter AS m USING (matter_id)
INNER JOIN dim_timekeeper AS t
    ON v.timekeeper_id = t.timekeeper_id
    AND v.work_date >= t.valid_from
    AND v.work_date < t.valid_to;

CREATE OR REPLACE VIEW v_time_current AS
SELECT * FROM fact_time WHERE is_active AND known_to = DATE '9999-12-31';

CREATE OR REPLACE TABLE fact_bill_line AS
SELECT
    b.bill_id,
    b.bill_date::DATE AS bill_date,
    date_trunc('month', b.bill_date)::DATE AS bill_month,
    b.entry_id,
    t.matter_id,
    t.unit_id,
    t.standard_value,
    t.net_value AS wip_cleared,
    b.billed_amount::DECIMAL(14, 2) AS billed_amount
FROM raw.bill_lines AS b
INNER JOIN v_time_current AS t USING (entry_id);

CREATE OR REPLACE TABLE fact_receipt AS
WITH bill AS (
    SELECT bill_id, any_value(matter_id) AS matter_id, any_value(unit_id) AS unit_id
    FROM fact_bill_line
    GROUP BY bill_id
)
SELECT
    r.receipt_id,
    r.bill_id,
    b.matter_id,
    b.unit_id,
    r.receipt_date::DATE AS receipt_date,
    date_trunc('month', r.receipt_date)::DATE AS receipt_month,
    r.amount::DECIMAL(14, 2) AS amount,
    r.kind
FROM raw.receipts AS r
INNER JOIN bill AS b USING (bill_id);
