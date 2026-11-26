import hashlib

import duckdb
import pytest

from trust_attendance_bi.calendar import BANK_HOLIDAYS, INSET_DAYS, TERMS, school_days
from trust_attendance_bi.generate import generate
from trust_attendance_bi.warehouse import BuildError, build


def test_calendar_has_190_teaching_days_and_no_holidays():
    days = school_days()
    assert len(days) == 190
    dates = {d.day for d in days}
    assert not dates & (BANK_HOLIDAYS | INSET_DAYS)
    for term in TERMS:
        assert not any(term.half_term[0] <= d <= term.half_term[1] for d in dates)
        assert term.start <= term.census <= term.end
    assert all(d.day.weekday() < 5 for d in days)
    assert [d.week_of_year for d in days] == sorted(d.week_of_year for d in days)


def test_generator_is_deterministic(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    generate(a, seed=3, scale=0.05)
    generate(b, seed=3, scale=0.05)
    for name in ("pupils.csv", "characteristics.csv", "enrolments.csv"):
        assert (
            hashlib.sha256((a / name).read_bytes()).digest()
            == hashlib.sha256((b / name).read_bytes()).digest()
        )
    q = "SELECT count(*), sum(hash(pupil_id || code || session)) FROM '{}'"
    assert (
        duckdb.sql(q.format(a / "marks.parquet")).fetchall()
        == duckdb.sql(q.format(b / "marks.parquet")).fetchall()
    )


def test_every_blocking_check_passes(built):
    _, report = built
    assert report.failed_blocking == []
    assert {c["check_name"] for c in report.checks} >= {
        "one mark per pupil, day and session",
        "week aggregate reconciles to fact",
    }


def test_raw_faults_are_handled(con):
    raw, dedup = con.execute(
        "SELECT (SELECT count(*) FROM raw_marks), (SELECT count(*) FROM stg_marks_dedup)"
    ).fetchone()
    assert raw > dedup  # export duplicates removed
    reasons = dict(
        con.execute("SELECT reject_reason, count(*) FROM quarantine_marks GROUP BY 1").fetchall()
    )
    assert reasons.keys() == {"unknown attendance code", "pupil not on roll"}
    assert (
        con.execute("SELECT count(*) FROM fact_attendance_session WHERE code = 'Z'").fetchone()[0]
        == 0
    )


def test_latest_valid_mark_wins_over_first_entry_and_corrupt_rows(con):
    # Sessions first entered as N and later explained must end with the explanation.
    row = con.execute(
        """
        SELECT count(*) FILTER (WHERE f.code = 'N'), count(*)
        FROM fact_attendance_session f
        JOIN (SELECT pupil_id, mark_date, session FROM stg_marks_dedup
              GROUP BY ALL HAVING count(*) FILTER (WHERE code = 'N') > 0 AND count(*) > 1) a
          ON f.pupil_id = a.pupil_id AND f.date = a.mark_date AND f.session = a.session
        """
    ).fetchone()
    assert row[1] > 0 and row[0] < row[1] * 0.2  # most N marks were replaced by a reason
    corrupt_keys = con.execute(
        """
        SELECT count(*) FROM quarantine_marks q
        JOIN fact_attendance_session f ON f.pupil_id = q.pupil_id AND f.date = q.mark_date
         AND f.session = q.session
        WHERE q.reject_reason = 'unknown attendance code'
        """
    ).fetchone()[0]
    assert corrupt_keys > 0  # the good earlier mark survived the corrupt later one


def test_scd2_ranges_never_overlap_and_cover_every_change(con):
    overlaps = con.execute(
        """
        SELECT count(*) FROM dim_pupil a JOIN dim_pupil b
          ON a.pupil_id = b.pupil_id AND a.pupil_key < b.pupil_key
         AND a.valid_from <= b.valid_to AND b.valid_from <= a.valid_to
        """
    ).fetchone()[0]
    assert overlaps == 0
    changes = con.execute("SELECT count(*) FROM raw_characteristics").fetchone()[0]
    assert con.execute("SELECT count(*) FROM dim_pupil").fetchone()[0] == changes


def test_characteristics_are_taken_at_census_day(con):
    # Pupils whose FSM status changed after the autumn census keep their census status
    # for every autumn session.
    bad = con.execute(
        """
        WITH later AS (
            SELECT d.pupil_id, d.fsm FROM dim_pupil d
            WHERE d.valid_from > DATE '2025-10-02' AND d.valid_from <= DATE '2025-12-19'
        )
        SELECT count(*) FROM fact_attendance_session f
        JOIN bridge_pupil_term b ON b.pupil_id = f.pupil_id AND b.term = f.term
        WHERE f.term = 'Autumn' AND f.fsm <> b.fsm
        """
    ).fetchone()[0]
    assert bad == 0
    one_status = con.execute(
        """SELECT max(n) FROM (SELECT count(DISTINCT fsm) n FROM fact_attendance_session
           GROUP BY pupil_id, term)"""
    ).fetchone()[0]
    assert one_status == 1


def test_closures_and_missing_registers_are_not_possible_sessions(con):
    row = con.execute(
        "SELECT sum(possible), sum(missing) FROM fact_attendance_session WHERE code IN ('Y', '-')"
    ).fetchone()
    assert row[0] == 0 and row[1] > 0


def test_build_needs_every_raw_file(tmp_path):
    with pytest.raises(BuildError, match="missing raw files"):
        build(tmp_path)


def test_each_build_is_recorded(con):
    run = con.execute("SELECT fact_rows, checks_failed FROM meta_runs").fetchone()
    assert run[0] == con.execute("SELECT count(*) FROM fact_attendance_session").fetchone()[0]
    assert run[1] == 0
