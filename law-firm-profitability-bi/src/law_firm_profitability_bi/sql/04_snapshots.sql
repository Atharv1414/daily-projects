-- Periodic snapshot: one row per matter per month. Balances are running totals of the ledger,
-- so every row satisfies opening + movement = closing.
CREATE OR REPLACE TABLE fact_matter_month AS
WITH movement AS (
    SELECT matter_id, date_trunc('month', known_from)::DATE AS month_start,
        net_value AS recorded, 0::DECIMAL(14, 2) AS cleared, 0::DECIMAL(14, 2) AS billed,
        0::DECIMAL(14, 2) AS settled
    FROM v_time_current
    UNION ALL
    SELECT matter_id, bill_month, 0, wip_cleared, billed_amount, 0 FROM fact_bill_line
    UNION ALL
    SELECT matter_id, receipt_month, 0, 0, 0, amount FROM fact_receipt
),

monthly AS (
    SELECT
        d.month_start,
        m.matter_id,
        m.unit_id,
        coalesce(sum(v.recorded), 0) AS recorded,
        coalesce(sum(v.cleared), 0) AS cleared,
        coalesce(sum(v.billed), 0) AS billed,
        coalesce(sum(v.settled), 0) AS settled
    FROM dim_matter AS m
    INNER JOIN dim_month AS d ON date_trunc('month', m.opened_date) <= d.month_start
    LEFT JOIN movement AS v ON v.matter_id = m.matter_id AND v.month_start = d.month_start
    GROUP BY ALL
)

SELECT
    *,
    sum(recorded - cleared) OVER running AS closing_wip,
    sum(billed - settled) OVER running AS closing_debt,
    sum(billed) OVER (running ROWS BETWEEN 2 PRECEDING AND CURRENT ROW) AS billed_3m
FROM monthly
WINDOW running AS (PARTITION BY matter_id ORDER BY month_start);

-- Accumulating snapshot: one row per matter, filled in as it passes each milestone.
CREATE OR REPLACE TABLE fact_matter_lifecycle AS
WITH worked AS (
    SELECT matter_id, min(work_date) AS first_time, sum(net_value) AS recorded,
        sum(cost_value) AS cost
    FROM v_time_current GROUP BY matter_id
),

billed AS (
    SELECT matter_id, min(bill_date) AS first_bill, sum(billed_amount) AS billed
    FROM fact_bill_line GROUP BY matter_id
),

paid AS (
    SELECT matter_id, min(receipt_date) AS first_cash, sum(amount) AS cash
    FROM fact_receipt WHERE kind = 'cash' GROUP BY matter_id
)

SELECT
    m.*,
    w.first_time,
    b.first_bill,
    p.first_cash,
    date_diff('day', m.opened_date, w.first_time) AS days_to_time,
    date_diff('day', w.first_time, b.first_bill) AS days_to_bill,
    date_diff('day', b.first_bill, p.first_cash) AS days_to_cash,
    coalesce(w.recorded, 0) AS recorded,
    coalesce(w.cost, 0) AS cost,
    coalesce(b.billed, 0) AS billed,
    coalesce(p.cash, 0) AS cash
FROM dim_matter AS m
LEFT JOIN worked AS w USING (matter_id)
LEFT JOIN billed AS b USING (matter_id)
LEFT JOIN paid AS p USING (matter_id);
