-- Data-quality checks recorded with every build. Each row: check, observed value, limit and
-- whether it passed. The build fails if a "blocking" check fails.

CREATE OR REPLACE TABLE dq_checks AS
WITH
totals AS (
    SELECT
        sum(possible) AS possible,
        sum(present) AS present,
        sum(authorised) AS authorised,
        sum(unauthorised) AS unauthorised,
        sum(missing) AS missing,
        count(*) AS marks
    FROM fact_attendance_session
),

checks AS (
    SELECT
        'one mark per pupil, day and session' AS check_name,
        (
            SELECT count(*) FROM (
                SELECT 1
                FROM fact_attendance_session
                GROUP BY pupil_id, date, session
                HAVING count(*) > 1
            )
        )::DOUBLE AS observed,
        0.0 AS limit_value,
        TRUE AS blocking
    UNION ALL
    SELECT
        'possible = present + authorised + unauthorised',
        abs(possible - present - authorised - unauthorised)::DOUBLE,
        0.0,
        TRUE
    FROM totals
    UNION ALL
    SELECT
        'every staged mark reaches the fact',
        abs((SELECT count(*) FROM stg_marks) - (SELECT marks FROM totals))::DOUBLE,
        0.0,
        TRUE
    UNION ALL
    SELECT
        'week aggregate reconciles to fact',
        abs((SELECT sum(possible) FROM agg_group_week) - (SELECT possible FROM totals))::DOUBLE,
        0.0,
        TRUE
    UNION ALL
    SELECT
        'pupil-term aggregate reconciles to fact',
        abs((SELECT sum(present) FROM agg_pupil_term) - (SELECT present FROM totals))::DOUBLE,
        0.0,
        TRUE
    UNION ALL
    SELECT
        'every pupil has exactly one current SCD2 row',
        (
            SELECT count(*) FROM (
                SELECT pupil_id
                FROM dim_pupil
                GROUP BY pupil_id
                HAVING count(*) FILTER (WHERE is_current) <> 1
            )
        )::DOUBLE,
        0.0,
        TRUE
    UNION ALL
    SELECT
        'share of sessions with no register taken (%)',
        round(100.0 * missing / marks, 3),
        0.5,
        FALSE
    FROM totals
    UNION ALL
    SELECT
        'share of raw rows quarantined (%)',
        round(
            100.0 * (SELECT count(*) FROM quarantine_marks)
            / (SELECT count(*) FROM stg_marks_dedup),
            3
        ),
        0.1,
        FALSE
    UNION ALL
    SELECT
        'absences still coded N, no reason (%)',
        round(
            100.0 * (SELECT count(*) FROM fact_attendance_session WHERE code = 'N')
            / nullif(authorised + unauthorised, 0),
            2
        ),
        5.0,
        FALSE
    FROM totals
)

SELECT
    check_name,
    observed,
    limit_value,
    blocking,
    observed <= limit_value AS passed
FROM checks;
