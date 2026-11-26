"""Synthetic school-MIS exports for Carrow Valley Academy Trust (an invented trust).

Produces the files a trust's data team would actually receive, with their usual faults:

* ``schools.csv``, ``pupils.csv``, ``enrolments.csv`` (mid-year joiners and leavers)
* ``characteristics.csv``: dated changes to FSM eligibility and SEN status (for SCD Type 2)
* ``marks.parquet``: one row per register mark, AM and PM, with every amendment kept
  (absences are often entered as N "no reason yet" and corrected days later), plus export
  duplicates, a few corrupt codes and marks entered after a pupil left.

Absence is simulated as episodes (a Markov chain per pupil), so illness runs for several days,
with realistic patterns: more absence among disadvantaged pupils and in Years 9 to 11, on
Mondays and Fridays, in winter and in the last weeks of the summer term.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from .calendar import TERMS, school_days


@dataclass(frozen=True)
class School:
    id: str
    name: str
    phase: str  # Primary / Secondary
    pupils: int
    fsm_share: float
    effect: float  # school-level absence multiplier


SCHOOLS: tuple[School, ...] = (
    School("S01", "Wrenfield Primary", "Primary", 420, 0.14, 0.85),
    School("S02", "Brookhollow Primary", "Primary", 210, 0.31, 1.10),
    School("S03", "Kestrel Lane Primary", "Primary", 315, 0.22, 0.95),
    School("S04", "St Aldric's CE Primary", "Primary", 238, 0.09, 0.80),
    School("S05", "Carrow Bridge Primary", "Primary", 455, 0.38, 1.25),
    School("S06", "Carrow Valley Academy", "Secondary", 1380, 0.29, 1.10),
    School("S07", "Ellerby Park Academy", "Secondary", 1050, 0.18, 0.90),
    School("S08", "Whitlow Green Academy", "Secondary", 860, 0.41, 1.35),
)

PRIMARY_YEARS = ("R", "1", "2", "3", "4", "5", "6")
SECONDARY_YEARS = ("7", "8", "9", "10", "11")
YEAR_FACTOR = {
    "R": 1.15,
    "1": 1.0,
    "2": 0.95,
    "3": 0.92,
    "4": 0.92,
    "5": 0.95,
    "6": 0.98,
    "7": 1.0,
    "8": 1.15,
    "9": 1.3,
    "10": 1.42,
    "11": 1.35,
}

# Reasons for a whole-day absence episode, with relative weights and whether they continue.
REASONS = ("I", "M", "C", "O", "G", "U", "E", "R")
REASON_WEIGHTS = np.array([0.60, 0.07, 0.05, 0.12, 0.08, 0.04, 0.02, 0.02])
SNOW_DAY = ("S02", "2026-01-07")  # Brookhollow closed for snow: code Y, not a possible session

FIRST = (
    "Ava",
    "Noah",
    "Isla",
    "Leo",
    "Amara",
    "Musa",
    "Ruby",
    "Oscar",
    "Zara",
    "Alfie",
    "Maya",
    "Theo",
    "Aisha",
    "Jack",
    "Ivy",
    "Yusuf",
    "Freya",
    "Kai",
    "Poppy",
    "Ibrahim",
)


def _school_pupils(rng: np.random.Generator, school: School, scale: float, start: int):
    years = PRIMARY_YEARS if school.phase == "Primary" else SECONDARY_YEARS
    n = max(len(years) * 6, int(round(school.pupils * scale)))
    year = np.array([years[i % len(years)] for i in range(n)])
    sen = rng.choice(["None", "SEN support", "EHCP"], size=n, p=[0.84, 0.135, 0.025])
    ids = [f"P{start + i:06d}" for i in range(n)]
    birth_base = {y: 2020 - (0 if y == "R" else int(y)) for y in years}
    return pd.DataFrame(
        {
            "pupil_id": ids,
            "school_id": school.id,
            "year_group": year,
            "sex": rng.choice(["F", "M"], size=n),
            "birth_year": [birth_base[y] - 1 for y in year],
            "fsm": rng.random(n) < school.fsm_share,
            "sen": sen,
            "eal": rng.random(n) < 0.17,
            "first_name": rng.choice(FIRST, size=n),
        }
    )


def generate(out_dir: Path, seed: int = 26, scale: float = 1.0) -> dict[str, int]:
    """Writes the raw files to ``out_dir`` and returns row counts."""
    out_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    days = school_days()
    n_days = len(days)
    day_dates = np.array([d.day for d in days])

    frames, start = [], 1
    for school in SCHOOLS:
        df = _school_pupils(rng, school, scale, start)
        start += len(df)
        frames.append(df)
    pupils = pd.concat(frames, ignore_index=True)
    n = len(pupils)

    # ---- enrolment windows (indices into the school-day list, inclusive) ---------------
    join_idx = np.zeros(n, dtype=int)
    leave_idx = np.full(n, n_days - 1, dtype=int)
    joiners = rng.random(n) < 0.06
    leavers = (rng.random(n) < 0.05) & ~joiners
    join_idx[joiners] = rng.integers(10, 170, joiners.sum())
    leave_idx[leavers] = rng.integers(20, 180, leavers.sum())
    enrolments = pd.DataFrame(
        {
            "pupil_id": pupils.pupil_id,
            "school_id": pupils.school_id,
            "entry_date": [days[i].day for i in join_idx],
            "leaving_date": [days[i].day if leavers[k] else None for k, i in enumerate(leave_idx)],
        }
    )

    # ---- characteristic history: initial status plus dated changes (SCD2 source) -------
    rows = [
        (p, days[j].day, bool(f), s)
        for p, j, f, s in zip(pupils.pupil_id, join_idx, pupils.fsm, pupils.sen, strict=True)
    ]
    fsm_change = rng.random(n) < 0.06
    sen_change = rng.random(n) < 0.035
    for k in np.flatnonzero(fsm_change | sen_change):
        when = (
            int(rng.integers(join_idx[k] + 5, n_days - 5)) if join_idx[k] + 5 < n_days - 5 else None
        )
        if when is None or when > leave_idx[k]:
            continue
        fsm = bool(pupils.fsm[k]) ^ bool(fsm_change[k])
        sen = pupils.sen[k]
        if sen_change[k]:
            sen = (
                "SEN support"
                if sen == "None"
                else ("EHCP" if sen == "SEN support" else "SEN support")
            )
        rows.append((pupils.pupil_id[k], days[when].day, fsm, sen))
    characteristics = pd.DataFrame(rows, columns=["pupil_id", "effective_date", "fsm", "sen"])

    # ---- absence propensity --------------------------------------------------------------
    school_effect = pupils.school_id.map({s.id: s.effect for s in SCHOOLS}).to_numpy()
    base = rng.beta(1.6, 38, n)
    chronic = rng.random(n) < 0.035
    base[chronic] = rng.uniform(0.12, 0.3, chronic.sum())
    fsm_now = pupils.fsm.to_numpy()
    sen_mult = pupils.sen.map({"None": 1.0, "SEN support": 1.4, "EHCP": 1.75}).to_numpy()
    year_mult = pupils.year_group.map(YEAR_FACTOR).to_numpy()
    propensity = base * np.where(fsm_now, 1.7, 1.0) * sen_mult * year_mult * school_effect

    weekday = np.array([d.day.weekday() for d in days])
    month = np.array([d.day.month for d in days])
    day_mult = np.select([weekday == 0, weekday == 4], [1.12, 1.25], 1.0) * np.select(
        [np.isin(month, [1, 2]), month == 12, month == 7], [1.3, 1.2, 1.35], 1.0
    )
    # Days just before a holiday attract unauthorised family holidays.
    pre_holiday = np.zeros(n_days, dtype=bool)
    for term in TERMS:
        for i, d in enumerate(days):
            to_half = (term.half_term[0] - d.day).days
            to_end = (term.end - d.day).days
            if 0 < to_half <= 7 or 0 <= to_end <= 7:
                pre_holiday[i] = True

    absent = np.zeros((n, n_days), dtype=bool)
    reason = np.zeros((n, n_days), dtype=np.int8)
    prev = np.zeros(n, dtype=bool)
    prev_reason = np.zeros(n, dtype=np.int8)
    for t in range(n_days):
        p_start = np.clip(propensity * day_mult[t] * 0.45, 0, 0.9)
        cont = rng.random(n) < np.where(chronic, 0.7, 0.55)
        # M, U and R are one-day reasons; illness, holiday and others can run on.
        can_continue = ~np.isin(prev_reason, [1, 5, 7])
        today = np.where(prev & can_continue, cont, rng.random(n) < p_start)
        weights = REASON_WEIGHTS.copy()
        if pre_holiday[t]:
            weights[4] *= 4
        new_reason = rng.choice(len(REASONS), size=n, p=weights / weights.sum())
        new_reason = np.where(
            (new_reason == 6) & np.isin(pupils.year_group.to_numpy(), PRIMARY_YEARS),
            0,
            new_reason,
        )  # exclusions are rare in primary: treat as illness
        r = np.where(prev & today & can_continue, prev_reason, new_reason).astype(np.int8)
        absent[:, t] = today
        reason[:, t] = np.where(today, r, 0)
        prev, prev_reason = today, reason[:, t]

    on_roll = (np.arange(n_days)[None, :] >= join_idx[:, None]) & (
        np.arange(n_days)[None, :] <= leave_idx[:, None]
    )

    # ---- register marks, AM and PM -------------------------------------------------------
    am = np.where(absent, np.array(REASONS)[reason], "/").astype(object)
    pm = np.where(absent, np.array(REASONS)[reason], "\\").astype(object)
    present = ~absent
    late = present & (rng.random((n, n_days)) < 0.03)
    am[late] = "L"
    offsite = present & ~late & (rng.random((n, n_days)) < 0.005)
    am[offsite] = "B"
    pm[offsite] = "B"
    appt = present & (rng.random((n, n_days)) < 0.008)
    pm[appt] = "M"
    late_closed = present & ~late & (rng.random((n, n_days)) < 0.006)
    am[late_closed] = "U"
    snow = (pupils.school_id.to_numpy() == SNOW_DAY[0])[:, None] & (
        np.array([str(d) for d in day_dates]) == SNOW_DAY[1]
    )[None, :]
    am[snow] = "Y"
    pm[snow] = "Y"
    missing = rng.random((n, n_days, 2)) < 0.002
    am[missing[:, :, 0]] = "-"
    pm[missing[:, :, 1]] = "-"

    pi, di = np.nonzero(on_roll)
    pupil_ids = pupils.pupil_id.to_numpy()
    school_ids = pupils.school_id.to_numpy()
    base_ts = np.array([datetime.combine(d, time(8, 55)) for d in day_dates], dtype="datetime64[s]")
    pm_offset = np.timedelta64(4 * 3600 + 20 * 60, "s")
    marks = pd.DataFrame(
        {
            "pupil_id": np.concatenate([pupil_ids[pi], pupil_ids[pi]]),
            "school_id": np.concatenate([school_ids[pi], school_ids[pi]]),
            "mark_date": np.concatenate([day_dates[di], day_dates[di]]),
            "session": np.repeat(np.array(["AM", "PM"]), len(pi)),
            "code": np.concatenate([am[pi, di], pm[pi, di]]),
            "recorded_at": np.concatenate([base_ts[di], base_ts[di] + pm_offset]),
        }
    )

    # Absences first entered as N (no reason yet) and amended a few school days later.
    is_absence = marks.code.isin(REASONS).to_numpy()
    unexplained = is_absence & (rng.random(len(marks)) < 0.4)
    first = marks[unexplained].copy()
    first["code"] = "N"
    amended = (
        marks.loc[unexplained, "recorded_at"]
        + pd.to_timedelta(rng.integers(1, 6, unexplained.sum()), unit="D")
        + pd.to_timedelta(rng.integers(0, 8 * 3600, unexplained.sum()), unit="s")
    )
    marks.loc[unexplained, "recorded_at"] = amended
    # Some never get a reason: they stay N, which counts as unauthorised.
    stay_n = first.sample(frac=0.1, random_state=seed).index
    marks.loc[stay_n, "code"] = "N"

    # Faults: export duplicates, corrupt codes, marks after a pupil has left.
    dupes = marks.sample(frac=0.004, random_state=seed + 1)
    corrupt = marks.sample(n=max(1, int(len(marks) * 0.0001)), random_state=seed + 2).copy()
    corrupt["code"] = "Z"
    corrupt["recorded_at"] = corrupt["recorded_at"] + pd.Timedelta(hours=1)
    ghost_rows = []
    for k in np.flatnonzero(leavers)[: max(1, leavers.sum() // 20)]:
        for extra in range(1, 4):
            i = leave_idx[k] + extra
            if i < n_days:
                ghost_rows.append(
                    (
                        pupil_ids[k],
                        school_ids[k],
                        day_dates[i],
                        "AM",
                        "/",
                        datetime.combine(day_dates[i], time(8, 55)),
                    )
                )
    ghosts = pd.DataFrame(ghost_rows, columns=marks.columns)
    marks = pd.concat([marks, first, dupes, corrupt, ghosts], ignore_index=True)
    marks = marks.sample(frac=1.0, random_state=seed + 3).reset_index(drop=True)

    schools = pd.DataFrame([s.__dict__ for s in SCHOOLS]).drop(columns=["effect", "fsm_share"])
    schools = schools.rename(columns={"pupils": "capacity"})
    schools.to_csv(out_dir / "schools.csv", index=False)
    pupils.drop(columns=["fsm", "sen"]).to_csv(out_dir / "pupils.csv", index=False)
    enrolments.to_csv(out_dir / "enrolments.csv", index=False)
    characteristics.to_csv(out_dir / "characteristics.csv", index=False)
    con = duckdb.connect()
    con.register("marks_df", marks)
    con.execute(
        f"COPY (SELECT * FROM marks_df) TO '{(out_dir / 'marks.parquet').as_posix()}' "
        "(FORMAT parquet, COMPRESSION zstd)"
    )
    con.close()
    return {
        "schools": len(schools),
        "pupils": n,
        "characteristics": len(characteristics),
        "marks": len(marks),
    }
