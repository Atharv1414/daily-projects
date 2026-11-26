-- Dimensions: school, pupil (SCD Type 2) and the census-date bridge that fixes each pupil's
-- characteristics for a term.

CREATE OR REPLACE TABLE dim_school AS
SELECT
    id AS school_id,
    name AS school_name,
    phase,
    capacity
FROM raw_schools;

-- SCD Type 2: one row per pupil per period with unchanged FSM and SEN status. valid_to is the
-- day before the next change; the open row ends on 9999-12-31.
CREATE OR REPLACE TABLE dim_pupil AS
WITH ordered AS (
    SELECT
        c.pupil_id,
        c.effective_date,
        c.fsm,
        c.sen,
        lead(c.effective_date) OVER (
            PARTITION BY c.pupil_id ORDER BY c.effective_date
        ) AS next_change
    FROM raw_characteristics AS c
)

SELECT
    row_number() OVER (ORDER BY o.pupil_id, o.effective_date) AS pupil_key,
    o.pupil_id,
    p.school_id,
    p.year_group,
    p.sex,
    p.eal,
    o.fsm,
    o.sen,
    o.effective_date AS valid_from,
    coalesce(o.next_change - INTERVAL 1 DAY, DATE '9999-12-31')::DATE AS valid_to,
    o.next_change IS NULL AS is_current
FROM ordered AS o
INNER JOIN raw_pupils AS p ON o.pupil_id = p.pupil_id;

-- Characteristics are reported as at the termly school census, as the DfE does, so a pupil
-- has one FSM and SEN status per term and every aggregate adds up to the same totals. A pupil
-- who joins after census day takes their status on entry; one who leaves before it, their
-- status on leaving.
CREATE OR REPLACE TABLE bridge_pupil_term AS
WITH on_roll AS (
    SELECT
        e.pupil_id,
        t.term,
        t.census,
        greatest(t.census, e.entry_date) AS joined_by_census,
        coalesce(e.leaving_date, DATE '9999-12-31') AS left_on
    FROM raw_enrolments AS e
    INNER JOIN dim_term AS t
        ON
            e.entry_date <= t.term_end
            AND coalesce(e.leaving_date, DATE '9999-12-31') >= t.term_start
),

as_at AS (
    SELECT
        pupil_id,
        term,
        least(joined_by_census, left_on) AS as_at_date
    FROM on_roll
)

SELECT
    a.pupil_id,
    a.term,
    a.as_at_date,
    dp.pupil_key,
    dp.school_id,
    s.phase,
    dp.year_group,
    dp.sex,
    dp.fsm,
    dp.sen
FROM as_at AS a
INNER JOIN dim_pupil AS dp
    ON
        a.pupil_id = dp.pupil_id
        AND a.as_at_date BETWEEN dp.valid_from AND dp.valid_to
INNER JOIN dim_school AS s ON dp.school_id = s.school_id;
