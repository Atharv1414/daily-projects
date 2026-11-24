"""Renders charts and the written business case from an analysis."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from . import finance, mining  # noqa: E402
from .model import CLOCKS  # noqa: E402
from .pipeline import BASE, DIGITAL, RECOMMENDED, STRESS, Analysis  # noqa: E402

BLUE, ORANGE, RED, GREY = "#2a78d6", "#eb6834", "#e34948", "#898781"
GRID, MUTED, SURFACE = "#e1e0d9", "#52514e", "#fcfcfb"


def _axes(title: str, height: float = 4.2) -> tuple[plt.Figure, plt.Axes]:
    fig, ax = plt.subplots(figsize=(9, height), dpi=130)
    fig.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, loc="left", fontsize=12, pad=14)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, length=0, labelsize=9)
    ax.set_axisbelow(True)
    return fig, ax


def _save(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)


def charts(a: Analysis, folder: Path) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)

    table = a.compliance.iloc[::-1]
    fig, ax = _axes("Statutory clocks met, as-is (from the cleaned event log)", 3.4)
    ax.barh(table.clock, table.met_share * 100, color=BLUE, height=0.55)
    for i, share in enumerate(table.met_share):
        ax.annotate(f"{share:.1%}", (share * 100, i), xytext=(5, 0), va="center",
                    textcoords="offset points", fontsize=9)  # fmt: skip
    ax.set_xlim(0, 112)
    ax.xaxis.set_visible(False)
    _save(fig, folder / "compliance.png")

    months = mining.investigation_by_month(a.log, a.records)
    months = months[months.index >= "2025-11"]
    fig, ax = _axes("Significant hazards investigated within 10 working days, by month reported")
    ax.plot(range(len(months)), months * 100, color=BLUE, linewidth=2, marker="o", markersize=6)
    low = int(months.to_numpy().argmin())
    ax.annotate(f"{months.iloc[low]:.0%}", (low, months.iloc[low] * 100), xytext=(0, -16),
                textcoords="offset points", ha="center", fontsize=9)  # fmt: skip
    ax.set_xticks(range(len(months)), months.index)
    ax.set_ylim(60, 102)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.grid(axis="y", color=GRID)
    _save(fig, folder / "winter_backlog.png")

    parts = mining.time_breakdown(a.log)
    parts = parts[parts.wait > 0.05].iloc[::-1]
    fig, ax = _axes("Where a case spends its time (working days per closed case)", 3.8)
    ax.barh(parts.index, parts.wait, color=ORANGE, height=0.55, label="Waiting before")
    ax.barh(parts.index, parts.work, left=parts.wait, color=BLUE, height=0.55, label="Working",
            edgecolor=SURFACE)  # fmt: skip
    for i, (wait, work) in enumerate(zip(parts.wait, parts.work, strict=True)):
        ax.annotate(f"{wait:.1f} + {work:.2f}", (wait + work, i), xytext=(5, 0), va="center",
                    textcoords="offset points", fontsize=9)  # fmt: skip
    ax.set_xlim(0, parts.wait.max() * 1.25)
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.grid(axis="x", color=GRID)
    _save(fig, folder / "waiting.png")

    names = list(a.runs)
    share = [a.mean(n, "compliant_share") for n in names]
    fig, ax = _axes("Simulated: cases with every clock met (95% CI)", 3.6)
    y = range(len(names))
    colours = [BLUE if n == RECOMMENDED else GREY for n in names]
    ax.barh(y, [s.mean * 100 for s in share], color=colours, height=0.55)
    for i, s in enumerate(share):
        ax.plot([s.low * 100, s.high * 100], [i, i], color="#0b0b0b", linewidth=1.5)
        ax.annotate(f"{s.mean:.1%}", (max(s.high, s.mean) * 100, i), xytext=(6, 0), va="center",
                    textcoords="offset points", fontsize=9)  # fmt: skip
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_xlim(0, 112)
    ax.xaxis.set_visible(False)
    _save(fig, folder / "scenarios.png")

    fig, ax = _axes("Five-year NPV against doing nothing", 3.6)
    others = [n for n in names if n != BASE]
    values = [finance.option_npv(a.options[n], a.assumptions) / 1e6 for n in others]
    ax.barh(range(len(others)), values, height=0.55,
            color=[BLUE if v >= 0 else RED for v in values])  # fmt: skip
    for i, v in enumerate(values):
        ax.annotate(_money(v * 1e6), (v, i), xytext=(5 if v >= 0 else -5, 0), va="center",
                    ha="left" if v >= 0 else "right", textcoords="offset points", fontsize=9)  # fmt: skip # noqa: E501
    span = max(values) - min(min(values), 0)
    ax.set_xlim(min(min(values), 0) - span * 0.18, max(values) + span * 0.18)
    ax.axvline(0, color=MUTED, linewidth=1)
    ax.set_yticks(range(len(others)), others)
    ax.invert_yaxis()
    ax.xaxis.set_visible(False)
    _save(fig, folder / "npv.png")

    swings = finance.tornado(a.options[RECOMMENDED], a.assumptions)[:7][::-1]
    base = finance.option_npv(a.options[RECOMMENDED], a.assumptions) / 1e6
    fig, ax = _axes(f"{RECOMMENDED}: NPV when each assumption moves ±30%")
    for i, s in enumerate(swings):
        for value, colour in ((s.low / 1e6, ORANGE), (s.high / 1e6, BLUE)):
            ax.barh(i, value - base, left=base, color=colour, height=0.55)
    ax.barh(0, 0, color=ORANGE, label="assumption −30%")
    ax.barh(0, 0, color=BLUE, label="assumption +30%")
    ax.axvline(base, color=MUTED, linewidth=1)
    ax.set_yticks(range(len(swings)), [s.assumption.replace("_", " ") for s in swings])
    ax.xaxis.set_major_formatter(lambda v, _: f"£{v:.1f}m")
    ax.legend(frameon=False, loc="lower right", fontsize=9)
    ax.grid(axis="x", color=GRID)
    _save(fig, folder / "tornado.png")
    return sorted(folder.glob("*.png"))


def _money(value: float) -> str:
    sign = "−" if value < 0 else ""
    size = abs(value)
    return f"{sign}£{size / 1e6:.2f}m" if size >= 1e6 else f"{sign}£{size / 1e3:,.0f}k"


def _avg(values: list[float]) -> float:
    return sum(values) / len(values)


def _rows(header: list[str], rows: list[list[str]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    return [*lines, *("| " + " | ".join(r) + " |" for r in rows), ""]


def options_table(a: Analysis) -> list[str]:
    rows = []
    for name in a.runs:
        option, flows = a.options[name], finance.cash_flows(a.options[name], a.assumptions)
        irr, pay = finance.irr(flows), finance.payback_years(flows)
        share = a.mean(name, "compliant_share")
        rows.append(
            [
                name,
                f"{share.mean:.1%} ({share.low:.1%} to {share.high:.1%})",
                f"{a.mean(name, 'breached_cases').mean:,.0f}",
                f"{a.mean(name, 'mean_days').mean:.1f}",
                "–" if name == BASE else _money(finance.option_npv(option, a.assumptions)),
                "–" if irr is None else f"{irr:.0%}",
                "–" if pay is None else f"{pay:.1f} years",
            ]
        )
    header = ["Option", "All clocks met (95% CI)", "Breached cases a year", "Mean working days",
              "NPV", "IRR", "Payback"]  # fmt: skip
    return _rows(header, rows)


def business_case(a: Analysis) -> str:
    observed, s = a.observed(), a.assumptions
    option = a.options[RECOMMENDED]
    npv = finance.option_npv(option, s)
    digital = finance.option_npv(a.options[DIGITAL], s)
    even = finance.break_even_breach_cost(option, s)
    base, best = a.mean(BASE, "compliant_share"), a.mean(RECOMMENDED, "compliant_share")
    drop = a.change(RECOMMENDED, "breached_cases")
    freed = (
        (a.mean(BASE, "use_surveyor").mean - a.mean(DIGITAL, "use_surveyor").mean)
        * a.parameters.surveyors
    )  # fmt: skip
    out = [
        "# Business case: damp and mould repairs",
        "",
        "Generated by `damp-case report`. Synthetic data for a fictional housing association;",
        "statutory limits are simplified and this is not legal advice.",
        "",
        "## Executive summary",
        "",
        f"**Recommendation: approve option {RECOMMENDED}.** Two queues cause most breaches: "
        "make-safe jobs wait behind routine repairs, and written summaries wait for one "
        f"administrator. Fixing both is simulated to raise cases meeting every clock from "
        f"{base.mean:.0%} to {best.mean:.1%}, avoiding {-drop.mean:,.0f} breached cases a year "
        f"(95% CI {-drop.high:,.0f} to {-drop.low:,.0f}). Five-year NPV is {_money(npv)}.",
        "",
        f"**The full digital programme is not justified on compliance alone.** It reaches "
        f"{a.mean(DIGITAL, 'compliant_share').mean:.1%}, but its NPV is {_money(digital)}, "
        f"which is {_money(npv - digital)} less. What it adds is fewer failed visits "
        f"({a.mean(BASE, 'no_access_visits').mean:,.0f} to "
        f"{a.mean(DIGITAL, 'no_access_visits').mean:,.0f} a year) and about {freed:.1f} full-time "
        "surveyors of capacity, not counted as a saving because no post is removed. Treat it as "
        "phase 2, with its own decision.",
        "",
        f"The case rests on the cost of a breached case, assumed to be £{s.breach_cost:,.0f}. The "
        f"recommended option breaks even at £{even:,.0f}. It does not shorten the end-to-end time "
        f"({a.mean(BASE, 'mean_days').mean:.1f} to {a.mean(RECOMMENDED, 'mean_days').mean:.1f} "
        "working days): it reorders waiting so that hazards are dealt with first. Only more crews "
        "shorten the wait.",
        "",
        "## Current state",
        "",
        f"{a.log.cases:,} cases over a year. Step-level fitness to policy is "
        f"{a.conformance.fitness:.1%}, but only {a.conformance.conforming_cases:.1%} of cases "
        "follow it throughout.",
        "",
        *_rows(
            ["Clock", "Cases", "Met", "Breached"],
            [[r.clock, f"{r.cases:,}", f"{r.met_share:.1%}", f"{r.breached:,}"]
             for r in a.compliance.itertuples()],
        ),
        "![Compliance](charts/compliance.png)",
        "![Waiting](charts/waiting.png)",
        "",
        "```mermaid",
        "flowchart LR",
        *_process_map(a),
        "```",
        "",
        "Policy departures:",
        "",
        *_rows(
            ["Departure", "Cases"], [[v, f"{n:,}"] for v, n in a.conformance.violations[:6]]
        ),
        "## Data cleaning log",
        "",
        *_rows(["Step", "Rows"], [[n, f"{c:,}"] for n, c in a.log.notes]),
        "## Does the model reproduce today?",
        "",
        *_rows(
            ["Measure", "Event log", "Calibrated simulation (95% CI)"],
            [[k, f"{v:,.3f}",
              f"{a.mean(BASE, k).mean:,.3f} ({a.mean(BASE, k).low:,.3f} to "
              f"{a.mean(BASE, k).high:,.3f})"] for k, v in observed.items()],
        ),
        "The log is one possible year and the interval is for the *average* year, so some log",
        "values fall outside it. Teams close to full capacity make queues very sensitive to luck.",
        "",
        "## Options",
        "",
        *options_table(a),
        "![Scenarios](charts/scenarios.png)",
        "![NPV](charts/npv.png)",
        "![Tornado](charts/tornado.png)",
        "",
        f"## Stress test: {STRESS - 1:.0%} more demand",
        "",
        *_rows(
            ["Option", "All clocks met", "Breached cases", "Mean working days", "Open at year end"],
            [
                [n, f"{_avg(r['compliant_share']):.1%}", f"{_avg(r['breached_cases']):,.0f}",
                 f"{_avg(r['mean_days']):.1f}", f"{_avg(r['still_open']):,.0f}"]
                for n, r in a.stressed.items()
            ],
        ),
        "## Future state",
        "",
        "```mermaid",
        "flowchart LR",
        "  R[Report] --> T[Triage] -->|emergency| Q",
        "  T -->|other| SQ{{Survey queue, earliest deadline first}} --> S[Survey]",
        "  S --> L{{Summary queue, two administrators}} --> LS[Summary sent]",
        "  S --> Q{{Works queue, earliest deadline first}}",
        "  Q --> M[Make safe] --> P[Repair] --> I[Inspect] --> C[Close with evidence check]",
        "```",
        "",
        "## Stakeholders",
        "",
        *_rows(
            ["Stakeholder", "Interest", "Influence", "Need", "Engagement"],
            [[p["name"], p["interest"], p["influence"], p["need"], p["engage"]]
             for p in a.content.stakeholders],
        ),
        "## RACI",
        "",
        *_rows(
            ["Activity", *a.content.raci_roles],
            [[name, *(c or " " for c in codes)] for name, codes in a.content.raci.items()],
        ),
        "## Risks",
        "",
        *_rows(
            ["Id", "Risk", "Score", "Mitigation", "Owner"],
            [[r["id"], r["text"], str(r["probability"] * r["impact"]), r["mitigation"], r["owner"]]
             for r in sorted(a.content.risks, key=lambda r: -r["probability"] * r["impact"])],
        ),
        "## Assumptions",
        "",
        *_rows(
            ["Assumption", "Value"],
            [[f.name.replace("_", " "), f"{getattr(s, f.name):,}"]
             for f in finance.fields(s)],
        ),
    ]  # fmt: skip
    return "\n".join(out)


def _process_map(a: Analysis) -> list[str]:
    edges = [e for e in mining.directly_follows(a.log) if e.count >= 100]
    ids: dict[str, str] = {}
    lines = []
    for e in edges:
        for name in (e.source, e.target):
            if name not in ids:
                ids[name] = f"n{len(ids)}"
                lines.append(f'  {ids[name]}["{name}"]')
        wait = "" if e.median_wait_days != e.median_wait_days else f", {e.median_wait_days:.1f}d"
        lines.append(f'  {ids[e.source]} -->|"{e.count:,}{wait}"| {ids[e.target]}')
    return lines


def requirements(a: Analysis) -> str:
    rows = []
    for story in a.content.stories:
        value, met = a.story_result(story)
        verdict = "not modelled" if met is None else "met" if met else "NOT MET"
        shown = "–" if value is None else f"{value:,.3f}" if value <= 1 else f"{value:,.1f}"
        pains = ", ".join(story.solves)
        rows.append([story.id, story.priority, str(story.points), pains, story.want, story.kpi,
                     f"{story.target:g}", str(story.phase), shown, verdict])  # fmt: skip
    out = ["# Requirements and traceability", "", "## Pain points", ""]
    out += _rows(
        ["Id", "Pain point", "Evidence metric"],
        [[p["id"], p["text"], p["metric"]] for p in a.content.pain_points.values()],
    )
    header = ["Story", "Priority", "Points", "Solves", "Want", "KPI", "Target",
              "Phase", "Simulated", "Verdict"]  # fmt: skip
    out += ["## Traceability matrix", "", *_rows(header, rows), "## Stories", ""]
    for s in a.content.stories:
        out += [f"**{s.id} ({s.priority}).** As a {s.role}, I want {s.want}, so that {s.so}.", ""]
    return "\n".join(out)


def feature_file(a: Analysis) -> str:
    body = "\n".join(s.gherkin() for s in a.content.in_scope)
    return f"Feature: Damp and mould cases meet their statutory clocks\n\n{body}"


def write_all(a: Analysis, folder: Path) -> list[Path]:
    paths = charts(a, folder / "charts")
    for name, text in (
        ("BUSINESS_CASE.md", business_case(a)),
        ("REQUIREMENTS.md", requirements(a)),
        ("acceptance.feature", feature_file(a)),
    ):
        (folder / name).write_text(text + "\n")
        paths.append(folder / name)
    return paths


def clock_summary(a: Analysis) -> list[str]:
    lines = [f"{'clock':<36}{'log':>8}{'A':>8}{'D':>8}"]
    observed = a.observed()
    for c in CLOCKS:
        key = f"met_{c.key}"
        now, best = a.mean(BASE, key).mean, a.mean(RECOMMENDED, key).mean
        lines.append(f"{c.label:<36}{observed[key]:>8.1%}{now:>8.1%}{best:>8.1%}")
    return lines
