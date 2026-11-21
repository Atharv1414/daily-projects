"""Run and data-quality reporting: Markdown summary plus PNG charts."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from smart_meter_lakehouse.dag import RunResult  # noqa: E402

PRICE_CAP_CHANGE = date(2026, 10, 1)


def run_summary(result: RunResult, ctx: dict) -> str:
    lines = [f"run {result.run_id}: {result.status.upper()}"]
    for name, t in result.tasks.items():
        extra = f" rows={t.rows}" if t.rows is not None else ""
        retry = f" attempts={t.attempts}" if t.attempts > 1 else ""
        err = f"  <- {t.error}" if t.error else ""
        lines.append(f"  {name:<17} {t.status:<8} {t.seconds:>6.2f}s{extra}{retry}{err}")
    for src, s in ctx.get("ingest", {}).items():
        lines.append(
            f"  ingest {src:<10} loaded={len(s.loaded)} skipped={len(s.skipped)} "
            f"rejected={len(s.rejected)} rows={s.rows:,}"
        )
    for src, s in ctx.get("silver", {}).items():
        if s.checked:
            lines.append(
                f"  silver {src:<10} checked={s.checked:,} rejected={s.rejected:,} "
                f"({s.error_rate:.2%}) upserted={s.upserted:,}"
            )
    if "gold" in ctx:
        g = ctx["gold"]
        lines.append(
            f"  gold   dates={g.affected_dates} halfhour_rows={g.halfhour_rows:,} "
            f"daily_rows={g.daily_rows:,}"
        )
    return "\n".join(lines)


def dq_table(con: duckdb.DuckDBPyConnection) -> list[tuple]:
    return con.execute("""
        SELECT source, rule, severity, SUM(failed) AS failed, SUM(checked) AS checked,
               ROUND(100.0 * SUM(failed) / NULLIF(SUM(checked), 0), 3) AS pct
        FROM silver.dq_results GROUP BY 1, 2, 3 ORDER BY source, severity, failed DESC
    """).fetchall()


def write_report(con: duckdb.DuckDBPyConnection, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = dq_table(con)
    files = con.execute(
        "SELECT status, COUNT(*) FROM meta.ingest_log GROUP BY 1 ORDER BY 1"
    ).fetchall()
    late = con.execute("SELECT COUNT(*) FROM meta.ingest_log WHERE late_file").fetchone()[0]
    counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in (
            "bronze.readings",
            "silver.readings",
            "silver.quarantine",
            "gold.dim_customer",
            "gold.fact_halfhour",
            "gold.fact_daily_meter",
        )
    }
    late_reads = con.execute("""SELECT COUNT(*) FROM silver.readings
        WHERE TRY_CAST(regexp_extract(_source_file, '(\\d{4}-\\d{2}-\\d{2})', 1) AS DATE)
              > CAST(read_at AS DATE)""").fetchone()[0]
    scd = con.execute(
        "SELECT COUNT(*) FILTER (WHERE NOT is_current), COUNT(DISTINCT "
        "customer_id) FROM gold.dim_customer"
    ).fetchone()
    md = [
        "# Data quality and load report",
        "",
        "## Row counts",
        "",
        "| Table | Rows |",
        "|---|---:|",
    ]
    md += [f"| `{t}` | {n:,} |" for t, n in counts.items()]
    md += [
        "",
        f"Files by status: {', '.join(f'{s}={n}' for s, n in files)}; "
        f"late files: {late}; late-arriving reads applied to earlier days: {late_reads:,}.",
        f"SCD2: {scd[1]:,} customers, {scd[0]:,} historical (closed) versions.",
        "",
        "## Rule results",
        "",
        "| Source | Rule | Severity | Failed | Checked | % |",
        "|---|---|---|---:|---:|---:|",
    ]
    md += [f"| {s} | {r} | {sev} | {f:,} | {c:,} | {p} |" for s, r, sev, f, c, p in rows]
    path = out_dir / "dq_report.md"
    path.write_text("\n".join(md) + "\n")
    _charts(con, out_dir, rows)
    return path


def _charts(con: duckdb.DuckDBPyConnection, out_dir: Path, rows: list[tuple]) -> None:
    daily = con.execute("""SELECT date, region, kwh / meters AS kwh_per_meter
                           FROM gold.v_region_daily ORDER BY date""").fetchall()
    if daily:
        fig, ax = plt.subplots(figsize=(10, 4.5))
        for region in ("London", "North West", "Yorkshire", "Scotland North", "South West"):
            pts = [(d, v) for d, r, v in daily if r == region]
            if pts:
                ax.plot([p[0] for p in pts], [p[1] for p in pts], label=region, linewidth=1.6)
        ax.set_title("Average daily consumption per meter by region (kWh)")
        ax.set_ylabel("kWh per meter per day")
        ax.axvline(x=PRICE_CAP_CHANGE, color="grey", linestyle="--", linewidth=0.8)
        ax.text(
            PRICE_CAP_CHANGE,
            ax.get_ylim()[1] * 0.97,
            " price cap change",
            fontsize=8,
            color="grey",
            va="top",
        )
        ax.legend(fontsize=8, ncol=5, loc="lower left")
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()
        fig.tight_layout()
        fig.savefig(out_dir / "consumption_by_region.png", dpi=110)
        plt.close(fig)
    errors = [(r, f) for s, r, sev, f, c, p in rows if sev == "error" and f]
    if errors:
        fig, ax = plt.subplots(figsize=(8, 4))
        labels = [f"{r}" for r, _ in errors]
        ax.barh(labels, [f for _, f in errors], color="#c0392b")
        ax.set_title("Rows quarantined by rule (all sources)")
        ax.set_xlabel("rows")
        for i, (_, f) in enumerate(errors):
            ax.text(f, i, f" {f:,}", va="center", fontsize=8)
        fig.tight_layout()
        fig.savefig(out_dir / "quarantine_by_rule.png", dpi=110)
        plt.close(fig)
    hh = con.execute(
        """SELECT period, AVG(kwh) FROM gold.fact_halfhour f
                        JOIN gold.dim_tariff t USING (tariff_sk)
                        WHERE t.tariff_code = ? GROUP BY 1 ORDER BY 1""",
        ["EV-NIGHT"],
    ).fetchall()
    std = con.execute(
        """SELECT period, AVG(kwh) FROM gold.fact_halfhour f
                         JOIN gold.dim_tariff t USING (tariff_sk)
                         WHERE t.tariff_code = ? GROUP BY 1 ORDER BY 1""",
        ["FLEX-STD"],
    ).fetchall()
    if hh and std:
        fig, ax = plt.subplots(figsize=(9, 4))
        ax.plot([p / 2 - 0.5 for p, _ in std], [v for _, v in std], label="FLEX-STD")
        ax.plot([p / 2 - 0.5 for p, _ in hh], [v for _, v in hh], label="EV-NIGHT")
        ax.set_title("Average half-hourly load profile by tariff (UTC)")
        ax.set_xlabel("hour of day (UTC)")
        ax.set_ylabel("kWh per half-hour")
        ax.legend()
        ax.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out_dir / "load_profile_by_tariff.png", dpi=110)
        plt.close(fig)
