-- Aggregates. Each holds only additive measures (session counts), so any coarser question can
-- be answered by summing them. Distinct pupils and thresholds such as persistent absence are
-- not additive and are only answered from the pupil-grain table.

CREATE OR REPLACE TABLE agg_group_week AS
SELECT
    school_id,
    phase,
    year_group,
    term,
    week_start,
    sex,
    fsm,
    sen,
    sum(possible) AS possible,
    sum(present) AS present,
    sum(authorised) AS authorised,
    sum(unauthorised) AS unauthorised,
    sum(missing) AS missing,
    sum(amended) AS amended,
    count(*) AS marks
FROM fact_attendance_session
GROUP BY ALL;

CREATE OR REPLACE TABLE agg_group_month AS
SELECT
    school_id,
    phase,
    year_group,
    term,
    month_start,
    sex,
    fsm,
    sen,
    sum(possible) AS possible,
    sum(present) AS present,
    sum(authorised) AS authorised,
    sum(unauthorised) AS unauthorised,
    sum(missing) AS missing,
    sum(amended) AS amended,
    count(*) AS marks
FROM fact_attendance_session
GROUP BY ALL;

CREATE OR REPLACE TABLE agg_group_term AS
SELECT
    school_id,
    phase,
    year_group,
    term,
    sex,
    fsm,
    sen,
    sum(possible) AS possible,
    sum(present) AS present,
    sum(authorised) AS authorised,
    sum(unauthorised) AS unauthorised,
    sum(missing) AS missing,
    sum(amended) AS amended,
    count(*) AS marks
FROM fact_attendance_session
GROUP BY ALL;

CREATE OR REPLACE TABLE agg_pupil_term AS
SELECT
    pupil_id,
    school_id,
    phase,
    year_group,
    term,
    sex,
    fsm,
    sen,
    sum(possible) AS possible,
    sum(present) AS present,
    sum(authorised) AS authorised,
    sum(unauthorised) AS unauthorised,
    sum(missing) AS missing,
    sum(amended) AS amended,
    count(*) AS marks
FROM fact_attendance_session
GROUP BY ALL;
