-- Raw layer: the MIS exports as delivered, typed but otherwise untouched.
-- {raw} is replaced with the raw data folder by warehouse.build().

CREATE OR REPLACE TABLE raw_schools AS
SELECT * FROM read_csv_auto('{raw}/schools.csv');

CREATE OR REPLACE TABLE raw_pupils AS
SELECT * FROM read_csv_auto('{raw}/pupils.csv', types = {'year_group': 'VARCHAR'});

CREATE OR REPLACE TABLE raw_enrolments AS
SELECT
    pupil_id,
    school_id,
    entry_date::DATE AS entry_date,
    leaving_date::DATE AS leaving_date
FROM read_csv_auto('{raw}/enrolments.csv');

CREATE OR REPLACE TABLE raw_characteristics AS
SELECT
    pupil_id,
    effective_date::DATE AS effective_date,
    fsm::BOOLEAN AS fsm,
    sen
FROM read_csv_auto('{raw}/characteristics.csv');

CREATE OR REPLACE TABLE raw_marks AS
SELECT
    pupil_id,
    school_id,
    mark_date::DATE AS mark_date,
    session,
    code,
    recorded_at::TIMESTAMP AS recorded_at
FROM read_parquet('{raw}/marks.parquet');
