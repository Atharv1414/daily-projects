import pytest
from hypothesis import given
from hypothesis import strategies as st

from hotel_revenue_agent.errors import SQLGuardError
from hotel_revenue_agent.sql_guard import FORBIDDEN_KEYWORDS, check_sql, guard, strip_noise


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select count(*) from bookings;",
        "WITH t AS (SELECT * FROM hotels) SELECT name FROM t",
        "SELECT 'DROP TABLE x' AS harmless_literal",
        "SELECT name -- trailing DELETE comment\nFROM hotels",
        'SELECT "updated" FROM (SELECT 1 AS "updated")',
    ],
)
def test_allows_read_queries(sql):
    assert check_sql(sql)


@pytest.mark.parametrize(
    "sql,fragment",
    [
        ("", "Empty"),
        ("   ", "Empty"),
        ("DROP TABLE bookings", "Only SELECT"),
        ("DELETE FROM bookings", "Only SELECT"),
        ("SELECT 1; DROP TABLE hotels", "Multiple statements"),
        ("SELECT 1 /* */; DROP TABLE hotels", "Multiple statements"),
        ("WITH x AS (SELECT 1) UPDATE bookings SET nights = 0", "UPDATE"),
        ("WITH x AS (SELECT 1) INSERT INTO hotels SELECT * FROM hotels", "INSERT"),
        ("SELECT * FROM sqlite_master", "SQLITE_MASTER"),
        ('SELECT * FROM "sqlite_master"', "SQLITE_MASTER"),
        ("SELECT load_extension('x')", "LOAD_EXTENSION"),
        ("PRAGMA journal_mode = OFF", "Only SELECT"),
        ("ATTACH DATABASE 'x.db' AS x", "Only SELECT"),
        ("SELECT 1 " + "x" * 6000, "longer"),
    ],
)
def test_blocks_unsafe_sql(sql, fragment):
    with pytest.raises(SQLGuardError, match=fragment):
        check_sql(sql)


def test_guard_wraps_with_limit_plus_one():
    g = guard("SELECT * FROM bookings;", max_rows=50)
    assert g.sql.endswith("LIMIT 51")
    assert "bookings" in g.sql


def test_strip_noise_removes_literals_and_comments():
    assert "DROP" not in strip_noise("SELECT 'DROP' /* DROP */ -- DROP")


@given(st.sampled_from(FORBIDDEN_KEYWORDS), st.text(alphabet="abc ()=1", max_size=20))
def test_forbidden_keyword_anywhere_outside_literals_is_rejected(keyword, filler):
    with pytest.raises(SQLGuardError):
        check_sql(f"SELECT {filler} {keyword} {filler}")


@given(st.text(max_size=200))
def test_guard_never_passes_non_select(text):
    try:
        cleaned = check_sql(text)
    except SQLGuardError:
        return
    first = strip_noise(cleaned).split(None, 1)[0].upper()
    assert first in {"SELECT", "WITH"}
