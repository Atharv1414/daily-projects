"""Static PNG charts for the README and briefings. Every number comes from the semantic layer,
so the charts, the dashboard and the CLI cannot disagree."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from .disclosure import suppress  # noqa: E402
from .semantic import MetricQuery, SemanticLayer  # noqa: E402

BLUE, ORANGE, INK, MUTED, GRID = "#2a78d6", "#eb6834", "#0b0b0b", "#52514e", "#e4e3df"
NAMES = {
    "S01": "Wrenfield",
    "S02": "Brookhollow",
    "S03": "Kestrel Lane",
    "S04": "St Aldric's",
    "S05": "Carrow Bridge",
    "S06": "Carrow Valley",
    "S07": "Ellerby Park",
    "S08": "Whitlow Green",
}


def _style(ax, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=13, color=INK, pad=12)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(colors=MUTED, length=0)


def render(sl: SemanticLayer, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.dpi": 110})
    written: list[Path] = []

    def save(fig, name: str) -> None:
        path = out_dir / name
        fig.tight_layout()
        fig.savefig(path, facecolor="white")
        plt.close(fig)
        written.append(path)

    # 1. Weekly attendance by phase
    df, _ = sl.query(MetricQuery(["attendance_rate"], ["phase", "week"]))
    fig, ax = plt.subplots(figsize=(9, 4))
    for phase, colour in (("Primary", BLUE), ("Secondary", ORANGE)):
        part = df[df.phase == phase]
        ax.plot(
            pd.to_datetime(part.week), part.attendance_rate, color=colour, linewidth=2, label=phase
        )
        ax.annotate(
            phase,
            (pd.to_datetime(part.week.iloc[-1]), part.attendance_rate.iloc[-1]),
            xytext=(6, 0),
            textcoords="offset points",
            color=INK,
            va="center",
        )
    _style(ax, "Weekly attendance, 2025/26: dips before Christmas and in July", "Attendance (%)")
    ax.legend(frameon=False, loc="lower left")
    save(fig, "weekly_attendance_by_phase.png")

    # 2. Persistent absence by school
    df, _ = sl.query(MetricQuery(["persistent_absence_rate", "pupils"], ["school"]))
    df = df.sort_values("persistent_absence_rate")
    fig, ax = plt.subplots(figsize=(9, 4.2))
    ax.barh([NAMES[s] for s in df.school], df.persistent_absence_rate, color=BLUE, height=0.6)
    for y, v in enumerate(df.persistent_absence_rate):
        ax.text(v + 0.4, y, f"{v:.1f}%", va="center", color=INK, fontsize=9)
    _style(ax, "Persistent absence (missed 10%+ of sessions) by school", "")
    ax.grid(axis="x", color=GRID)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("Pupils persistently absent (%)", color=MUTED)
    save(fig, "persistent_absence_by_school.png")

    # 3. Disadvantage gap: attendance FSM v not FSM, by school
    df, _ = sl.query(MetricQuery(["attendance_rate", "pupils"], ["school", "fsm"]))
    fig, ax = plt.subplots(figsize=(9, 4.2))
    schools = sorted(df.school.unique())
    xs = range(len(schools))
    # A dot plot, not bars: bars would have to start at zero and the gap would vanish.
    pairs = {
        s: (
            df[(df.school == s) & ~df.fsm].attendance_rate.iloc[0],
            df[(df.school == s) & df.fsm].attendance_rate.iloc[0],
        )
        for s in schools
    }
    for x, (not_fsm, fsm) in zip(xs, pairs.values(), strict=True):
        ax.plot([x, x], [fsm, not_fsm], color=GRID, linewidth=3, zorder=1)
        ax.text(
            x + 0.12,
            (fsm + not_fsm) / 2,
            f"{not_fsm - fsm:.1f}",
            color=MUTED,
            fontsize=9,
            va="center",
        )
    ax.scatter(
        list(xs),
        [v[0] for v in pairs.values()],
        s=70,
        color=BLUE,
        label="Not FSM",
        zorder=2,
        edgecolor="white",
        linewidth=1.5,
    )
    ax.scatter(
        list(xs),
        [v[1] for v in pairs.values()],
        s=70,
        color=ORANGE,
        label="FSM eligible",
        zorder=2,
        edgecolor="white",
        linewidth=1.5,
    )
    ax.set_xticks(list(xs), [NAMES[s] for s in schools], rotation=25, ha="right")
    _style(
        ax, "Attendance gap for pupils eligible for free school meals (points)", "Attendance (%)"
    )
    ax.legend(frameon=False, ncol=2, loc="upper left")
    save(fig, "fsm_gap_by_school.png")

    # 4. Absence reasons by month
    df, _ = sl.query(MetricQuery(["sessions_missed"], ["month", "code"]))
    df = df[df.sessions_missed > 0]
    groups = {
        "Illness (I)": ["I"],
        "Unauthorised (O, N, U)": ["O", "N", "U"],
        "Holiday not agreed (G)": ["G"],
        "Other authorised (M, C, E, R)": ["M", "C", "E", "R"],
    }
    months = sorted(df.month.unique())
    colours = [BLUE, ORANGE, "#1baf7a", "#eda100"]
    fig, ax = plt.subplots(figsize=(9, 4.2))
    bottom = [0.0] * len(months)
    for (label, codes), colour in zip(groups.items(), colours, strict=True):
        vals = [
            df[(df.month == m) & df.code.isin(codes)].sessions_missed.sum() / 1000 for m in months
        ]
        ax.bar(
            [pd.Timestamp(m).strftime("%b") for m in months],
            vals,
            bottom=bottom,
            color=colour,
            label=label,
            width=0.7,
            edgecolor="white",
            linewidth=1,
        )
        bottom = [b + v for b, v in zip(bottom, vals, strict=True)]
    _style(ax, "Sessions missed by reason and month", "Sessions missed (thousands)")
    ax.legend(frameon=False, fontsize=9, loc="upper right")
    save(fig, "absence_reasons_by_month.png")

    # 5. Weekday pattern
    df, _ = sl.query(MetricQuery(["absence_rate"], ["phase", "weekday"]))
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for offset, phase, colour in ((-0.18, "Primary", BLUE), (0.18, "Secondary", ORANGE)):
        part = df[df.phase == phase].set_index("weekday").loc[order]
        ax.bar(
            [i + offset for i in range(5)], part.absence_rate, width=0.34, color=colour, label=phase
        )
    ax.set_xticks(range(5), order)
    _style(ax, "Absence by day of the week: Fridays are worst", "Overall absence (%)")
    ax.legend(frameon=False, ncol=2, loc="upper left")
    save(fig, "absence_by_weekday.png")

    # 6. Year groups, with persistent absence, suppressed like a published table
    df, _ = sl.query(
        MetricQuery(["attendance_rate", "persistent_absence_rate", "pupils"], ["year_group"])
    )
    df = suppress(df, ["year_group"])
    fig, ax = plt.subplots(figsize=(9, 3.8))
    ax.bar(
        df.year_group.astype(str), df.persistent_absence_rate.astype(float), color=BLUE, width=0.6
    )
    _style(
        ax,
        "Persistent absence by year group: rising through secondary",
        "Pupils persistently absent (%)",
    )
    ax.set_xlabel("Year group (R = Reception)", color=MUTED)
    save(fig, "persistent_absence_by_year.png")
    return written
