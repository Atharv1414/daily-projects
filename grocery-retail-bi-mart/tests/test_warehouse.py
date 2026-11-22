from __future__ import annotations

from datetime import datetime

import pytest

from grocery_retail_bi.warehouse import WarehouseError, build, connect, land_raw, load_facts


def one(conn, sql, params=None):
    return conn.execute(sql, params or []).fetchall()[0][0]


def test_build_stats_and_batches(built):
    conn, stats = built
    assert len(stats["batches"]) == 3
    assert sum(b["rows_inserted"] for b in stats["batches"]) == stats["fact_rows"]
    assert stats["fact_rows"] == one(conn, "SELECT COUNT(*) FROM stg.sales_lines")


def test_rerun_is_idempotent(conn):
    before = one(conn, "SELECT COUNT(*) FROM mart.fact_sales_line")
    result = load_facts(conn)
    assert result.rows_inserted == 0
    assert one(conn, "SELECT COUNT(*) FROM mart.fact_sales_line") == before


def test_incremental_equals_full_build(raw_dir, conn):
    full, _ = build(raw_dir, ":memory:")
    q = "SELECT COUNT(*), SUM(net_amount), SUM(gross_margin) FROM mart.fact_sales_line"
    assert full.execute(q).fetchall() == conn.execute(q).fetchall()
    full.close()


def test_duplicates_removed_and_codes_cleaned(conn):
    assert one(conn, "SELECT COUNT(*) - COUNT(DISTINCT line_id) FROM raw.sales_lines") > 0
    assert one(conn, "SELECT COUNT(*) - COUNT(DISTINCT line_id) FROM stg.sales_lines") == 0
    assert (
        one(
            conn, "SELECT COUNT(*) FROM stg.sales_lines WHERE store_code <> upper(trim(store_code))"
        )
        == 0
    )


def test_late_arriving_lines_get_historical_versions(conn):
    late = one(conn, "SELECT SUM(late_rows) FROM mart.load_batches")
    assert late > 0
    bad = one(
        conn,
        """SELECT COUNT(*) FROM mart.fact_sales_line f
                       JOIN mart.dim_product p USING (product_sk) JOIN mart.dim_date d USING
                       (date_key) WHERE d.date NOT BETWEEN p.valid_from AND p.valid_to""",
    )
    assert bad == 0


def test_scd2_tracks_realignment_and_category_reorg(conn):
    moved = one(
        conn,
        """SELECT COUNT(DISTINCT store_code) FROM mart.dim_store
                         WHERE store_code IN (SELECT store_code FROM mart.dim_store
                                              WHERE region = 'North') AND region <> 'North'""",
    )
    assert moved > 0
    ready = conn.execute("""SELECT DISTINCT category FROM mart.dim_product
                            WHERE subcategory = 'Ready Meals' ORDER BY 1""").fetchall()
    assert [r[0] for r in ready] == ["Food To Go", "Frozen"]


def test_unknown_member_and_imputed_cost(conn):
    rows = conn.execute("""SELECT bool_and(is_cost_imputed), COUNT(*) FROM mart.fact_sales_line
                           WHERE product_sk = -1""").fetchall()[0]
    assert rows[1] > 0 and rows[0]


def test_returns_are_negative(conn):
    assert one(conn, "SELECT MAX(net_amount) FROM mart.fact_sales_line WHERE is_return") < 0


def test_store_month_view_windows(conn):
    row = conn.execute("""SELECT COUNT(*) FILTER (WHERE yoy_growth IS NOT NULL),
                                 COUNT(*) FILTER (WHERE rank_in_region = 1),
                                 COUNT(*) FILTER (WHERE is_lfl)
                          FROM mart.v_store_month""").fetchall()[0]
    assert all(v > 0 for v in row)


def test_missing_sources_raise(tmp_path):
    with pytest.raises(WarehouseError, match="missing source files"):
        land_raw(connect(), tmp_path)


def test_partial_cutoff_loads_subset(raw_dir):
    c, stats = build(raw_dir, ":memory:", [datetime(2025, 6, 30)])
    first = stats["batches"][0]
    assert 0 < first["rows_inserted"] < stats["fact_rows"]
    c.close()
