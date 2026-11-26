-- Fact: one row per pupil per session (about 1.8 million). Census-date attributes are copied
-- onto the fact so the common slices need no join; pupil_key still points at the SCD2 row.

CREATE OR REPLACE TABLE fact_attendance_session AS
SELECT
    m.pupil_id,
    b.pupil_key,
    d.date,
    d.term,
    d.week_start,
    d.month_start,
    d.weekday,
    m.session,
    m.code,
    b.school_id,
    b.phase,
    b.year_group,
    b.sex,
    b.fsm,
    b.sen,
    c.counts_as_possible::INTEGER AS possible,
    (c.category = 'present')::INTEGER AS present,
    (c.category = 'authorised')::INTEGER AS authorised,
    (c.category = 'unauthorised')::INTEGER AS unauthorised,
    (c.category = 'missing')::INTEGER AS missing,
    (m.versions > 1)::INTEGER AS amended
FROM stg_marks AS m
INNER JOIN ref_code AS c ON m.code = c.code
INNER JOIN dim_date AS d ON m.mark_date = d.date
INNER JOIN bridge_pupil_term AS b
    ON
        m.pupil_id = b.pupil_id
        AND d.term = b.term;
