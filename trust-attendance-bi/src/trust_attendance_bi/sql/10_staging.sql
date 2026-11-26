-- Staging: reference codes, de-duplication, validation with a quarantine, latest mark wins.

-- DfE attendance codes used by the trust. "counts_as_possible" decides whether a session is
-- in the denominator: Y (exceptional closure) and "-" (register not taken) are not.
CREATE OR REPLACE TABLE ref_code AS
SELECT *
FROM (
    VALUES
    ('/', 'Present (AM)', 'present', TRUE),
    ('\', 'Present (PM)', 'present', TRUE),
    ('L', 'Late, before registers closed', 'present', TRUE),
    ('B', 'Off-site educational activity', 'present', TRUE),
    ('I', 'Illness', 'authorised', TRUE),
    ('M', 'Medical or dental appointment', 'authorised', TRUE),
    ('C', 'Other authorised absence', 'authorised', TRUE),
    ('E', 'Suspended or excluded', 'authorised', TRUE),
    ('R', 'Religious observance', 'authorised', TRUE),
    ('O', 'Unauthorised absence', 'unauthorised', TRUE),
    ('G', 'Holiday not authorised', 'unauthorised', TRUE),
    ('U', 'Late, after registers closed', 'unauthorised', TRUE),
    ('N', 'No reason yet provided', 'unauthorised', TRUE),
    ('Y', 'School closed: exceptional circumstances', 'not_possible', FALSE),
    ('-', 'Register not taken', 'missing', FALSE)
) AS t (code, description, category, counts_as_possible);

-- Exact duplicate rows come from re-run MIS exports.
CREATE OR REPLACE TABLE stg_marks_dedup AS
SELECT DISTINCT
    pupil_id,
    school_id,
    mark_date,
    session,
    code,
    recorded_at
FROM raw_marks;

-- Every row gets a reason if it cannot be trusted. Validation happens before "latest wins",
-- so a corrupt late row cannot overwrite a good earlier one.
CREATE OR REPLACE TABLE stg_marks_checked AS
SELECT
    m.*,
    CASE
        WHEN c.code IS NULL THEN 'unknown attendance code'
        WHEN p.pupil_id IS NULL THEN 'unknown pupil'
        WHEN d.date IS NULL THEN 'not a school day'
        WHEN m.session NOT IN ('AM', 'PM') THEN 'unknown session'
        WHEN
            e.pupil_id IS NULL
            OR m.mark_date < e.entry_date
            OR m.mark_date > coalesce(e.leaving_date, DATE '9999-12-31')
            THEN 'pupil not on roll'
        WHEN m.school_id <> e.school_id THEN 'school does not match enrolment'
    END AS reject_reason
FROM stg_marks_dedup AS m
LEFT JOIN ref_code AS c ON m.code = c.code
LEFT JOIN raw_pupils AS p ON m.pupil_id = p.pupil_id
LEFT JOIN dim_date AS d ON m.mark_date = d.date
LEFT JOIN raw_enrolments AS e ON m.pupil_id = e.pupil_id;

CREATE OR REPLACE TABLE quarantine_marks AS
SELECT *
FROM stg_marks_checked
WHERE reject_reason IS NOT NULL;

-- One mark per pupil, day and session: the most recently recorded valid version. The number
-- of versions is kept, because "first entered as N" is itself a data-quality measure.
CREATE OR REPLACE TABLE stg_marks AS
SELECT
    pupil_id,
    school_id,
    mark_date,
    session,
    code,
    recorded_at,
    count(*) OVER (PARTITION BY pupil_id, mark_date, session) AS versions
FROM stg_marks_checked
WHERE reject_reason IS NULL
QUALIFY
    row_number() OVER (
        PARTITION BY pupil_id, mark_date, session
        ORDER BY recorded_at DESC, code ASC
    ) = 1;
