import duckdb
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from smart_meter_lakehouse.errors import SchemaError
from smart_meter_lakehouse.quality import READING_RULES, Rule, evaluate
from smart_meter_lakehouse.schema import MIGRATIONS, resolve_reading_schema
from smart_meter_lakehouse.transform import PARSE_READ_TS
from smart_meter_lakehouse.warehouse import connect, current_version, migrate


@pytest.mark.parametrize(
    "cols,version",
    [
        (["meter_id", "read_at", "kwh", "quality_flag"], 1),
        (["meter_id", "read_at", "consumption_kwh", "reading_type", "quality_flag"], 2),
        (["METER_ID", "read_at", "consumption_kwh", "reading_type", "quality_flag", "voltage"], 2),
    ],
)
def test_schema_registry_resolves_versions(cols, version):
    assert resolve_reading_schema(cols).version == version


def test_unknown_schema_rejected():
    with pytest.raises(SchemaError):
        resolve_reading_schema(["id", "value"])


def test_migrations_are_idempotent(tmp_path):
    path = tmp_path / "m.duckdb"
    con = connect(path)
    assert current_version(con) == len(MIGRATIONS)
    assert migrate(con) == []
    con.close()
    con = connect(path)  # reopen: nothing re-applied
    assert con.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == len(MIGRATIONS)
    con.close()


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-09-15T00:30:00Z", "2026-09-15 00:30:00"),
        ("15/09/2026 01:30", "2026-09-15 00:30:00"),  # BST local -> UTC
        ("2026-13-45T00:00:00Z", None),
        ("yesterday", None),
    ],
)
def test_timestamp_parsing_handles_utc_and_uk_local(raw, expected):
    con = duckdb.connect()
    got = con.execute(
        f"SELECT CAST({PARSE_READ_TS} AS VARCHAR) FROM (SELECT ? AS read_at)", [raw]
    ).fetchone()[0]
    assert got == expected


def _staging(con, rows):
    con.execute("""CREATE OR REPLACE TEMP TABLE stg AS SELECT * FROM (VALUES
        (NULL::VARCHAR, NULL::TIMESTAMP, NULL::DOUBLE, NULL::VARCHAR, NULL::VARCHAR,
         NULL::BIGINT, NULL::VARCHAR)) t(meter_id, read_ts, kwh_num, reading_type,
         _source_file, _line_no, _batch_id) WHERE FALSE""")
    con.executemany(
        "INSERT INTO stg VALUES (?, ?, ?, ?, 'f.csv', ?, 'b1')",
        [(*r, i) for i, r in enumerate(rows)],
    )


def test_evaluate_quarantines_errors_and_counts_warnings(con):
    con.execute(
        "INSERT INTO silver.customer_events VALUES ('c', TIMESTAMP '2026-01-01', 'A1', "
        "'M1', 'London', 'E1', 'FLEX-STD', false, 'b0', current_timestamp)"
    )
    _staging(
        con,
        [
            ("M1", "2026-09-15 00:00:00", 0.4, "A"),
            ("M1", "2026-09-15 00:30:00", -1.0, "A"),
            ("M1", "2026-09-15 01:00:00", 30.0, "A"),
            ("M9", "2026-09-15 01:30:00", 0.3, "E"),
            ("M1", "2026-09-15 02:15:00", 0.3, "A"),
            ("M1", "2026-09-15 03:00:00", 6.0, "E"),
        ],
    )
    out = evaluate(con, "stg", READING_RULES, "readings")
    assert out.checked == 6 and out.rejected_rows == 4
    assert out.failures["kwh_negative"] == 1 and out.failures["meter_unknown"] == 1
    assert out.failures["high_usage"] == 1 and out.failures["estimated_read"] == 2
    assert con.execute("SELECT COUNT(*) FROM silver.quarantine").fetchone()[0] == 4
    clean = con.execute("SELECT COUNT(*) FROM stg_checked WHERE NOT _rejected").fetchone()[0]
    assert clean == 2


@settings(max_examples=60, deadline=None)
@given(st.one_of(st.none(), st.floats(min_value=-50, max_value=50, allow_nan=False)))
def test_kwh_rules_property(value):
    con = duckdb.connect()
    con.execute("CREATE SCHEMA silver")
    con.execute(
        "CREATE TABLE silver.quarantine (source VARCHAR, rule VARCHAR, severity VARCHAR,"
        " record VARCHAR, _source_file VARCHAR, _line_no BIGINT, _batch_id VARCHAR, "
        "quarantined_at TIMESTAMP DEFAULT current_timestamp)"
    )
    con.execute(
        "CREATE TABLE silver.dq_results (batch_id VARCHAR, source VARCHAR, rule VARCHAR,"
        " severity VARCHAR, failed BIGINT, checked BIGINT)"
    )
    con.execute(
        "CREATE TEMP TABLE s AS SELECT ?::DOUBLE AS kwh_num, 'f' AS _source_file, "
        "1 AS _line_no, 'b' AS _batch_id",
        [value],
    )
    rules = [r for r in READING_RULES if r.name.startswith("kwh")]
    out = evaluate(con, "s", rules, "readings")
    expected_bad = value is None or value < 0 or value > 11.5
    assert (out.rejected_rows == 1) is expected_bad


def test_rule_with_null_predicate_counts_as_pass(con):
    con.execute(
        "CREATE TEMP TABLE n AS SELECT NULL::DOUBLE AS x, 'f' AS _source_file, "
        "1 AS _line_no, 'b' AS _batch_id"
    )
    out = evaluate(con, "n", [Rule("x_big", "error", "x > 1", "")], "t")
    assert out.rejected_rows == 0
