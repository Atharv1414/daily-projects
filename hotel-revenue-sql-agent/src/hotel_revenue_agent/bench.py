"""Micro-benchmark: guardrail overhead vs. query latency on the full warehouse."""

from __future__ import annotations

import statistics
import time

from hotel_revenue_agent.config import Settings
from hotel_revenue_agent.database import Warehouse
from hotel_revenue_agent.evals import ANSWER_CASES
from hotel_revenue_agent.sql_guard import check_sql


def run(settings: Settings, repeats: int = 2_000) -> dict[str, float]:
    sqls = [c.golden_sql for c in ANSWER_CASES if c.golden_sql]
    start = time.perf_counter()
    for _ in range(repeats):
        for sql in sqls:
            check_sql(sql)
    guard_us = (time.perf_counter() - start) / (repeats * len(sqls)) * 1e6
    wh = Warehouse(settings.db_path, settings.max_rows, settings.query_timeout_ms)
    try:
        latencies = []
        for sql in sqls:
            t = time.perf_counter()
            wh.query(sql)
            latencies.append((time.perf_counter() - t) * 1000)
    finally:
        wh.close()
    latencies.sort()
    return {
        "queries": len(sqls),
        "guard_us_per_query": round(guard_us, 1),
        "query_ms_median": round(statistics.median(latencies), 1),
        "query_ms_p95": round(latencies[max(0, int(0.95 * len(latencies)) - 1)], 1),
        "query_ms_max": round(latencies[-1], 1),
    }
