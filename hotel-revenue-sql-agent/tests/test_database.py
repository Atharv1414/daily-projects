import sqlite3

import pytest

from hotel_revenue_agent.database import Warehouse, make_authorizer
from hotel_revenue_agent.errors import SQLGuardError, ToolError


def test_list_tables_reports_counts(warehouse):
    tables = {t["table"]: t["rows"] for t in warehouse.list_tables()}
    assert tables["hotels"] == 12
    assert tables["bookings"] == 4_000


def test_query_truncates_and_flags(warehouse):
    warehouse.max_rows = 10
    result = warehouse.query("SELECT booking_id FROM bookings")
    assert result.row_count == 10
    assert result.truncated is True


def test_connection_is_read_only_even_without_guard(warehouse):
    with pytest.raises(sqlite3.OperationalError):
        warehouse._con.execute("DELETE FROM hotels")


def test_missing_column_gives_actionable_hint(warehouse):
    with pytest.raises(ToolError) as info:
        warehouse.query("SELECT revenue FROM bookings")
    assert "describe_table" in (info.value.hint or "")


def test_timeout_interrupts_runaway_query(settings):
    wh = Warehouse(settings.db_path, timeout_ms=50)
    try:
        with pytest.raises(ToolError, match="time limit"):
            wh.query(
                "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n) "
                "SELECT COUNT(*) FROM n"
            )
    finally:
        wh.close()


def test_explain_compiles_without_running(warehouse):
    plan = warehouse.explain("SELECT COUNT(*) FROM bookings WHERE hotel_id = 1")
    assert any("bookings" in line.lower() for line in plan)


def test_authorizer_blocks_sneaky_internal_reads(warehouse):
    # The keyword scan is the first line of defence; the authorizer is the second.
    with pytest.raises(SQLGuardError):
        warehouse.query("SELECT * FROM pragma_table_info('hotels')")


def test_unknown_table_rejected(warehouse):
    with pytest.raises(ToolError, match="Unknown table"):
        warehouse.describe_table("payroll")


def test_missing_database_file(tmp_path):
    with pytest.raises(ToolError, match="not found"):
        Warehouse(tmp_path / "nope.db")


def test_ctes_are_allowed_but_internals_are_not(warehouse):
    ok = warehouse.query("WITH t AS (SELECT hotel_id FROM hotels) SELECT COUNT(*) FROM t")
    assert ok.rows == [[12]]
    with pytest.raises(SQLGuardError):
        warehouse.query("WITH t AS (SELECT 1) SELECT * FROM sqlite_schema")


@pytest.mark.parametrize(
    "action,arg1,arg2,expected",
    [
        (sqlite3.SQLITE_FUNCTION, None, "load_extension", sqlite3.SQLITE_DENY),
        (sqlite3.SQLITE_FUNCTION, None, "sum", sqlite3.SQLITE_OK),
        (sqlite3.SQLITE_READ, "bookings", "nights", sqlite3.SQLITE_OK),
        (sqlite3.SQLITE_READ, "secret_table", "x", sqlite3.SQLITE_DENY),
        (sqlite3.SQLITE_READ, "my_cte", "x", sqlite3.SQLITE_OK),
        (sqlite3.SQLITE_INSERT, "bookings", None, sqlite3.SQLITE_DENY),
        (sqlite3.SQLITE_PRAGMA, "table_info", None, sqlite3.SQLITE_DENY),
    ],
)
def test_authorizer_decisions(action, arg1, arg2, expected):
    auth = make_authorizer(frozenset({"bookings", "secret_table"}))
    assert auth(action, arg1, arg2, "main", None) == expected
