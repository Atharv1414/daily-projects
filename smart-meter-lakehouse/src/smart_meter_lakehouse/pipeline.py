"""Wires sources, silver promotion and gold modelling into one DAG."""

from __future__ import annotations

from datetime import date
from typing import Any

import duckdb

from smart_meter_lakehouse import model, transform
from smart_meter_lakehouse.config import PipelineConfig
from smart_meter_lakehouse.dag import DAG, Runner, RunResult, Task
from smart_meter_lakehouse.errors import TransientSourceError
from smart_meter_lakehouse.ingest import ingest_source


class FlakyTariffAPI:
    """Simulates a rate-limited supplier API that fails ``failures`` times, then recovers."""

    def __init__(self, failures: int) -> None:
        self.remaining = failures
        self.calls = 0

    def __call__(self) -> None:
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise TransientSourceError("tariff API returned 503 Service Unavailable")


def build_dag(con: duckdb.DuckDBPyConnection, cfg: PipelineConfig) -> DAG:
    flaky = FlakyTariffAPI(cfg.flaky_tariff_failures)

    def ingest(source: str, before=None):
        def fn(ctx: dict[str, Any]) -> int:
            stats = ingest_source(
                con, cfg.landing_dir, source, ctx["through"], ctx["run_id"], before_load=before
            )
            ctx.setdefault("ingest", {})[source] = stats
            return stats.rows

        return fn

    def silver(name: str, fn):
        def run(ctx: dict[str, Any]) -> int:
            stats = fn()
            ctx.setdefault("silver", {})[name] = stats
            return stats.upserted

        return run

    def gold(ctx: dict[str, Any]) -> int:
        stats = model.build_facts(con, full_refresh=ctx.get("full_refresh", False))
        ctx["gold"] = stats
        return stats.halfhour_rows

    dag = DAG("smart_meter_daily")
    for src, out in [
        ("weather", "parquet"),
        ("tariffs", "json"),
        ("customers", "jsonl"),
        ("readings", "csv"),
    ]:
        dag.add(
            Task(
                f"ingest_{src}",
                ingest(src, flaky if src == "tariffs" else None),
                inputs=(f"landing/{src}_*.{out}",),
                outputs=(f"bronze.{src}",),
            )
        )
    dag.add(
        Task(
            "silver_weather",
            silver("weather", lambda: transform.promote_weather(con)),
            ("ingest_weather",),
            ("bronze.weather",),
            ("silver.weather",),
        )
    )
    dag.add(
        Task(
            "silver_tariffs",
            silver("tariffs", lambda: transform.promote_tariffs(con)),
            ("ingest_tariffs",),
            ("bronze.tariffs",),
            ("silver.tariffs",),
        )
    )
    dag.add(
        Task(
            "silver_customers",
            silver("customers", lambda: transform.promote_customers(con)),
            ("ingest_customers", "silver_tariffs"),
            ("bronze.customer_events",),
            ("silver.customer_events", "silver.quarantine"),
        )
    )
    dag.add(
        Task(
            "silver_readings",
            silver("readings", lambda: transform.promote_readings(con, cfg.max_error_rate)),
            ("ingest_readings", "silver_customers"),
            ("bronze.readings", "silver.customer_events"),
            ("silver.readings", "silver.quarantine"),
        )
    )
    dag.add(
        Task(
            "dim_date",
            lambda ctx: model.build_dim_date(con),
            ("silver_readings",),
            ("silver.readings",),
            ("gold.dim_date",),
        )
    )
    dag.add(
        Task(
            "dim_customer",
            lambda ctx: model.build_dim_customer(con),
            ("silver_customers",),
            ("silver.customer_events",),
            ("gold.dim_customer",),
        )
    )
    dag.add(
        Task(
            "dim_tariff",
            lambda ctx: model.build_dim_tariff(con),
            ("silver_tariffs",),
            ("silver.tariffs",),
            ("gold.dim_tariff",),
        )
    )
    dag.add(
        Task(
            "facts",
            gold,
            ("dim_date", "dim_customer", "dim_tariff", "silver_weather"),
            ("silver.readings", "gold.dim_customer", "gold.dim_tariff", "silver.weather"),
            ("gold.fact_halfhour", "gold.fact_daily_meter"),
        )
    )
    return dag


def run_pipeline(
    con: duckdb.DuckDBPyConnection,
    cfg: PipelineConfig,
    through: date,
    full_refresh: bool = False,
    sleep=None,
) -> tuple[RunResult, dict[str, Any]]:
    dag = build_dag(con, cfg)
    runner = Runner(
        con, cfg.max_retries, cfg.retry_backoff_s, **({"sleep": sleep} if sleep else {})
    )
    ctx: dict[str, Any] = {"through": through, "full_refresh": full_refresh}
    return runner.run(dag, ctx, through), ctx
