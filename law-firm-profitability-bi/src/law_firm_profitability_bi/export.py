"""Static artefacts: dashboard HTML, README charts and the validation report."""

from __future__ import annotations

from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .charts import BLUE, GREY, GRID, MUTED, ORANGE, RED, SURFACE
from .dashboard import render, static_views
from .metrics import FY25, FY26, Metrics, Period
from .security import USERS
from .validation import run_checks


def export_dashboards(con: duckdb.DuckDBPyConnection, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for name, view in static_views().items():
        path = folder / f"{name}.html"
        path.write_text(render(con, view))
        written.append(path)
    return written


def write_validation(con: duckdb.DuckDBPyConnection, path: Path) -> bool:
    checks = run_checks(con)
    lines = ["# Validation report", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {c.name} | {'pass' if c.ok else 'FAIL'} | {c.detail} |" for c in checks]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    return all(c.ok for c in checks)


def _axes(title: str) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(9, 4.2), dpi=130)
    fig.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, pad=14)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    return fig, ax


def _bridge(path: Path, title: str, steps: list[tuple[str, float, bool]]) -> None:
    fig, ax = _axes(title)
    level = 0.0
    for i, (_, amount, total) in enumerate(steps):
        bottom = 0.0 if total else min(level, level + amount)
        colour = GREY if total else BLUE if amount >= 0 else RED
        ax.bar(i, abs(amount) / 1e6, bottom=bottom / 1e6, color=colour, width=0.6)
        level = amount if total else level + amount
        top = max(level, bottom + abs(amount)) / 1e6
        label = (
            f"£{amount / 1e6:.2f}m"
            if total
            else f"{'+' if amount >= 0 else '−'}£{abs(amount) / 1e6:.2f}m"
        )  # noqa: E501
        ax.annotate(label, (i, top), xytext=(0, 4), textcoords="offset points", ha="center",
                    fontsize=9)  # fmt: skip
    ax.set_xticks(range(len(steps)), [s[0] for s in steps], fontsize=9)
    ax.yaxis.set_major_formatter(lambda v, _: f"£{v:.0f}m")
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def export_charts(con: duckdb.DuckDBPyConnection, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    metrics = Metrics(con, USERS["mp"])
    _bridge(
        folder / "waterfall.png",
        "FY26 bills: from standard value to cash",
        [(s["step"], s["amount"], s["kind"] == "total") for s in metrics.waterfall(FY26)],
    )
    v = metrics.variance(FY25, FY26)
    effects = [(k.title(), v[k], False) for k in ("volume", "mix", "rate", "discount")]
    _bridge(
        folder / "variance.png",
        "Why net value changed",
        [("FY25", v["base"], True), *effects, ("FY26", v["current"], True)],
    )

    rows = [r for r in metrics.lockup_trend(Period(FY25.start, FY26.end)) if r["lockup_days"]]
    fig, ax = _axes("Lock-up days by month")
    x = range(len(rows))
    wip = [r["wip_days"] for r in rows]
    ax.bar(x, wip, color=BLUE, label="WIP days", width=0.7, edgecolor=SURFACE)
    ax.bar(x, [r["debtor_days"] for r in rows], bottom=wip, color=ORANGE, label="Debtor days",
           width=0.7, edgecolor=SURFACE)  # fmt: skip
    ax.set_xticks(list(x)[::3], [r["month"][:7] for r in rows][::3], fontsize=9)
    ax.legend(frameon=False, loc="upper right", ncols=2, fontsize=9)
    ax.set_ylim(0, 150)
    fig.tight_layout()
    fig.savefig(folder / "lockup.png")
    plt.close(fig)

    leaves = [r["descendant_id"] for r in metrics._rows(
        """SELECT descendant_id FROM bridge_org WHERE ancestor_id = $unit AND descendant_id
        NOT IN (SELECT parent_id FROM dim_org WHERE parent_id IS NOT NULL)""", unit="FIRM"
    )]  # fmt: skip
    names = dict(con.execute("SELECT unit_id, unit_name FROM dim_org").fetchall())
    pairs = sorted(
        (
            metrics.kpis(FY26, u)["billing_realisation_pct"],
            metrics.kpis(FY25, u)["billing_realisation_pct"],
            names[u],
        )
        for u in leaves
    )
    fig, ax = _axes("Billing realisation by team: FY25 to FY26")
    for i, (new, old, _) in enumerate(pairs):
        ax.plot([old, new], [i, i], color=GRID, linewidth=2, zorder=1)
        ax.annotate(f"{new:.1f}%", (min(new, old), i), xytext=(-9, 0), ha="right", va="center",
                    textcoords="offset points", fontsize=9)  # fmt: skip
    ax.scatter([p[1] for p in pairs], range(len(pairs)), color=GREY, s=55, label="FY25", zorder=2)
    ax.scatter([p[0] for p in pairs], range(len(pairs)), color=BLUE, s=55, label="FY26", zorder=3)
    ax.set_yticks(range(len(pairs)), [p[2] for p in pairs], fontsize=9)
    ax.set_xlim(70, 100)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.grid(visible=False)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    fig.tight_layout()
    fig.savefig(folder / "realisation.png")
    plt.close(fig)
    return sorted(folder.glob("*.png"))
