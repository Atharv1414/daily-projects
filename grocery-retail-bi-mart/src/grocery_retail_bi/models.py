"""Documented SQL models for the dimensional warehouse, dbt-style.

Each model declares its dependencies; ``ordered()`` resolves a build order with a topological
sort and rejects cycles. Layers: ``stg`` (cleaned views over raw), ``mart`` (conformed
dimensions, facts and reporting views).
"""

from __future__ import annotations

from dataclasses import dataclass, field

UNKNOWN_SK = -1
NO_PROMO_SK = 0


@dataclass(frozen=True)
class Model:
    name: str
    kind: str  # "table" | "view"
    description: str
    sql: str
    depends_on: list[str] = field(default_factory=list)
    grain: str = ""


MODELS: list[Model] = [
    Model(
        "stg.sales_lines",
        "view",
        "Cleaned EPOS lines: trimmed/upper-cased store codes, de-duplicated on line_id (keeps "
        "the first load), sale_date derived, returns flagged.",
        """
        SELECT line_id, basket_id, upper(trim(store_code)) AS store_code,
               CAST(sale_ts AS TIMESTAMP) AS sale_ts, CAST(sale_ts AS DATE) AS sale_date,
               product_code, CAST(quantity AS INTEGER) AS quantity,
               CAST(unit_price AS DECIMAL(10, 2)) AS unit_price,
               CAST(discount_amount AS DECIMAL(12, 2)) AS discount_amount,
               CAST(net_amount AS DECIMAL(12, 2)) AS net_amount,
               NULLIF(promo_code, '') AS promo_code, loyalty_id,
               CAST(loaded_at AS TIMESTAMP) AS loaded_at, quantity < 0 AS is_return
        FROM raw.sales_lines
        QUALIFY row_number() OVER (PARTITION BY line_id ORDER BY loaded_at) = 1
        """,
        ["raw.sales_lines"],
        "one row per till line",
    ),
    Model(
        "mart.dim_date",
        "table",
        "Calendar dimension, Dec 2024 to Dec 2026, with ISO week and a March-start fiscal year.",
        """
        SELECT CAST(strftime(d, '%Y%m%d') AS INTEGER) AS date_key, CAST(d AS DATE) AS date,
               year(d) AS year, quarter(d) AS quarter, month(d) AS month,
               strftime(d, '%Y-%m') AS year_month, strftime(d, '%b') AS month_name,
               isoyear(d) AS iso_year, weekofyear(d) AS iso_week,
               isodow(d) AS day_of_week, strftime(d, '%a') AS day_name,
               isodow(d) >= 6 AS is_weekend,
               CASE WHEN month(d) >= 3 THEN year(d) + 1 ELSE year(d) END AS fiscal_year,
               CAST(date_trunc('month', d) AS DATE) AS month_start
        FROM range(DATE '2024-12-01', DATE '2027-01-01', INTERVAL 1 DAY) t(d)
        """,
        [],
        "one row per calendar day",
    ),
    Model(
        "mart.dim_store",
        "table",
        "Store dimension, SCD Type 2 built from monthly snapshots: a new version whenever the "
        "hash of tracked attributes (name, town, region, format, manager, size) changes.",
        """
        WITH s AS (
            SELECT *, md5(concat_ws('|', store_name, town, region, format, manager,
                                    size_sqft)) AS attr_hash
            FROM raw.stores_snapshot
        ), changes AS (
            SELECT *, lag(attr_hash) OVER (PARTITION BY store_code ORDER BY snapshot_date)
                      AS prev_hash
            FROM s
        ), versions AS (
            SELECT *,
                   row_number() OVER (PARTITION BY store_code ORDER BY snapshot_date)
                       AS version_no,
                   lead(snapshot_date) OVER (PARTITION BY store_code ORDER BY snapshot_date)
                       AS next_from
            FROM changes WHERE prev_hash IS NULL OR prev_hash <> attr_hash
        )
        SELECT CAST(row_number() OVER (ORDER BY store_code, snapshot_date) AS INTEGER)
                   AS store_sk,
               store_code, store_name, town, region, format, manager, size_sqft,
               CAST(opened_on AS DATE) AS opened_on, CAST(closed_on AS DATE) AS closed_on,
               CASE WHEN version_no = 1 THEN DATE '1900-01-01'
                    ELSE CAST(snapshot_date AS DATE) END AS valid_from,
               COALESCE(CAST(next_from AS DATE) - 1, DATE '9999-12-31') AS valid_to,
               next_from IS NULL AS is_current, version_no, attr_hash
        FROM versions
        """,
        ["raw.stores_snapshot"],
        "one row per store version",
    ),
    Model(
        "mart.dim_product",
        "table",
        "Product dimension, SCD Type 2 on category, brand, list price and unit cost, with an "
        "'Unknown' member (sk -1) for codes missing from the product master.",
        f"""
        WITH s AS (
            SELECT *, md5(concat_ws('|', product_name, category, subcategory, brand, own_label,
                                    base_price, unit_cost)) AS attr_hash
            FROM raw.products_snapshot
        ), changes AS (
            SELECT *, lag(attr_hash) OVER (PARTITION BY product_code ORDER BY snapshot_date)
                      AS prev_hash
            FROM s
        ), versions AS (
            SELECT *,
                   row_number() OVER (PARTITION BY product_code ORDER BY snapshot_date)
                       AS version_no,
                   lead(snapshot_date) OVER (PARTITION BY product_code ORDER BY snapshot_date)
                       AS next_from
            FROM changes WHERE prev_hash IS NULL OR prev_hash <> attr_hash
        )
        SELECT CAST(row_number() OVER (ORDER BY product_code, snapshot_date) AS INTEGER)
                   AS product_sk,
               product_code, product_name, category, subcategory, brand,
               CAST(own_label AS BOOLEAN) AS own_label,
               CAST(base_price AS DECIMAL(10, 2)) AS list_price,
               CAST(unit_cost AS DECIMAL(10, 2)) AS unit_cost,
               CASE WHEN version_no = 1 THEN DATE '1900-01-01'
                    ELSE CAST(snapshot_date AS DATE) END AS valid_from,
               COALESCE(CAST(next_from AS DATE) - 1, DATE '9999-12-31') AS valid_to,
               next_from IS NULL AS is_current, version_no, attr_hash
        FROM versions
        UNION ALL
        SELECT {UNKNOWN_SK}, 'UNKNOWN', 'Unknown product', 'Unknown', 'Unknown', 'Unknown',
               FALSE, NULL, NULL, DATE '1900-01-01', DATE '9999-12-31', TRUE, 1, NULL
        """,
        ["raw.products_snapshot"],
        "one row per product version",
    ),
    Model(
        "mart.dim_promotion",
        "table",
        "Promotion dimension from the trading calendar, plus a 'No promotion' member (sk 0).",
        f"""
        SELECT CAST(row_number() OVER (ORDER BY promo_code) AS INTEGER) AS promo_sk, promo_code,
               promo_name, mechanic, discount_pct, CAST(start_date AS DATE) AS start_date,
               CAST(end_date AS DATE) AS end_date
        FROM raw.promotions
        UNION ALL
        SELECT {NO_PROMO_SK}, 'NONE', 'No promotion', 'None', 0, NULL, NULL
        """,
        ["raw.promotions"],
        "one row per promotion",
    ),
    Model(
        "mart.bridge_promotion_product",
        "table",
        "Which products each promotion covered (many-to-many).",
        """
        SELECT promo_code, unnest(product_codes) AS product_code FROM raw.promotions
        """,
        ["raw.promotions"],
        "one row per promotion x product",
    ),
    Model(
        "mart.fact_store_target",
        "table",
        "Monthly sales targets from finance at store x month grain, keyed to the store version "
        "valid at the start of the month (point-in-time).",
        """
        SELECT CAST(strftime(CAST(t.month AS DATE), '%Y%m%d') AS INTEGER) AS month_key,
               ds.store_sk, t.store_code, CAST(t.target_net_sales AS DECIMAL(14, 2))
                   AS target_net_sales
        FROM raw.store_targets t
        JOIN mart.dim_store ds ON ds.store_code = t.store_code
             AND CAST(t.month AS DATE) BETWEEN ds.valid_from AND ds.valid_to
        """,
        ["raw.store_targets", "mart.dim_store"],
        "one row per store x month",
    ),
    Model(
        "mart.v_store_month",
        "view",
        "Store-month performance using CTEs and window functions: actual vs target, YoY "
        "growth via a 12-month lag, fiscal YTD running totals, rank within current region and "
        "a like-for-like flag (store trading for the full 13 months before the month).",
        """
        WITH actual AS (
            SELECT ds.store_code, d.month_start, d.fiscal_year,
                   SUM(f.net_amount) AS net_sales, SUM(f.gross_margin) AS gross_margin,
                   COUNT(DISTINCT f.basket_id) AS transactions
            FROM mart.fact_sales_line f
            JOIN mart.dim_store ds USING (store_sk)
            JOIN mart.dim_date d USING (date_key)
            GROUP BY ALL
        ), tgt AS (
            SELECT store_code, CAST(strptime(CAST(month_key AS VARCHAR), '%Y%m%d') AS DATE)
                       AS month_start, target_net_sales
            FROM mart.fact_store_target
        ), cur AS (
            SELECT store_code, store_name, region, format, opened_on, closed_on
            FROM mart.dim_store WHERE is_current
        ), joined AS (
            SELECT a.*, t.target_net_sales, c.store_name, c.region, c.format, c.opened_on,
                   c.closed_on
            FROM actual a
            LEFT JOIN tgt t USING (store_code, month_start)
            JOIN cur c USING (store_code)
        )
        SELECT *,
               net_sales - target_net_sales AS variance_to_target,
               net_sales / NULLIF(target_net_sales, 0) - 1 AS variance_pct,
               lag(net_sales, 12) OVER w AS net_sales_ly,
               net_sales / NULLIF(lag(net_sales, 12) OVER w, 0) - 1 AS yoy_growth,
               SUM(net_sales) OVER (PARTITION BY store_code, fiscal_year ORDER BY month_start
                                    ROWS UNBOUNDED PRECEDING) AS fytd_net_sales,
               rank() OVER (PARTITION BY region, month_start ORDER BY net_sales DESC)
                   AS rank_in_region,
               opened_on <= month_start - INTERVAL 13 MONTH
                   AND (closed_on IS NULL OR closed_on >= month_start + INTERVAL 1 MONTH)
                   AS is_lfl
        FROM joined
        WINDOW w AS (PARTITION BY store_code ORDER BY month_start)
        """,
        ["mart.fact_sales_line", "mart.dim_store", "mart.dim_date", "mart.fact_store_target"],
        "one row per store x month",
    ),
]

FACT_DDL = """
CREATE TABLE IF NOT EXISTS mart.fact_sales_line (
    line_id VARCHAR PRIMARY KEY,
    basket_id VARCHAR NOT NULL,
    date_key INTEGER NOT NULL,
    store_sk INTEGER NOT NULL,
    product_sk INTEGER NOT NULL,
    promo_sk INTEGER NOT NULL,
    is_loyalty BOOLEAN NOT NULL,
    is_return BOOLEAN NOT NULL,
    quantity INTEGER NOT NULL,
    discount_amount DECIMAL(12, 2) NOT NULL,
    net_amount DECIMAL(12, 2) NOT NULL,
    cost_amount DECIMAL(12, 2) NOT NULL,
    gross_margin DECIMAL(12, 2) NOT NULL,
    is_cost_imputed BOOLEAN NOT NULL,
    loaded_at TIMESTAMP NOT NULL,
    batch_id INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS mart.load_batches (
    batch_id INTEGER PRIMARY KEY,
    run_at TIMESTAMP NOT NULL,
    watermark_from TIMESTAMP NOT NULL,
    watermark_to TIMESTAMP,
    rows_inserted BIGINT NOT NULL,
    late_rows BIGINT NOT NULL
);
"""

# Incremental fact load. Point-in-time joins attach each line to the store/product version
# valid on the *sale date*, so late-arriving lines still land on the right historical version.
FACT_INSERT = f"""
INSERT INTO mart.fact_sales_line
SELECT s.line_id, s.basket_id, CAST(strftime(s.sale_date, '%Y%m%d') AS INTEGER),
       ds.store_sk, COALESCE(dp.product_sk, {UNKNOWN_SK}), COALESCE(pr.promo_sk, {NO_PROMO_SK}),
       s.loyalty_id IS NOT NULL, s.is_return, s.quantity, s.discount_amount, s.net_amount,
       COALESCE(s.quantity * dp.unit_cost, round(s.net_amount * 0.7, 2)),
       s.net_amount - COALESCE(s.quantity * dp.unit_cost, round(s.net_amount * 0.7, 2)),
       dp.unit_cost IS NULL, s.loaded_at, ?
FROM stg.sales_lines s
JOIN mart.dim_store ds ON ds.store_code = s.store_code
     AND s.sale_date BETWEEN ds.valid_from AND ds.valid_to
LEFT JOIN mart.dim_product dp ON dp.product_code = s.product_code
     AND s.sale_date BETWEEN dp.valid_from AND dp.valid_to
LEFT JOIN mart.dim_promotion pr ON pr.promo_code = s.promo_code
WHERE s.loaded_at > ? AND s.loaded_at <= ?
  AND NOT EXISTS (SELECT 1 FROM mart.fact_sales_line f WHERE f.line_id = s.line_id)
"""


class CycleError(ValueError):
    pass


def ordered(models: list[Model] = MODELS) -> list[Model]:
    """Topological sort (Kahn). Dependencies outside the model set (raw tables) are ignored."""
    by_name = {m.name: m for m in models}
    indeg = {m.name: sum(d in by_name for d in m.depends_on) for m in models}
    ready = sorted(n for n, k in indeg.items() if k == 0)
    out: list[Model] = []
    while ready:
        name = ready.pop(0)
        out.append(by_name[name])
        for m in models:
            if name in m.depends_on:
                indeg[m.name] -= 1
                if indeg[m.name] == 0:
                    ready.append(m.name)
                    ready.sort()
    if len(out) != len(models):
        stuck = sorted(n for n, k in indeg.items() if k > 0)
        raise CycleError(f"dependency cycle among: {', '.join(stuck)}")
    return out
