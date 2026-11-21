"""Seeded synthetic outpatient data for a fictional NHS acute trust ("Riverside NHS FT").

Four related tables written as CSV, shaped like a PAS (patient administration system)
extract: patients, clinics, appointments and an SMS reminder trial allocation table.

Attendance is simulated from a known logistic model (age, deprivation, lead time,
specialty, contact mode, weekday, season, a per-patient propensity and the trial arm), so
the analysis can be checked against the truth. The extract is deliberately messy: duplicate
rows from a system sync, inconsistent status labels, impossible ages, missing deprivation,
booking dates after the appointment, and orphan clinic codes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from outpatient_dna.config import TRIAL_END, TRIAL_START

SPECIALTIES = {
    # name: (share of activity, DNA log-odds effect)
    "Dermatology": (0.10, 0.10),
    "Cardiology": (0.11, -0.15),
    "Trauma & Orthopaedics": (0.14, -0.05),
    "Ophthalmology": (0.13, -0.30),
    "ENT": (0.09, 0.05),
    "Gastroenterology": (0.09, 0.20),
    "Paediatrics": (0.08, 0.25),
    "Mental Health": (0.06, 0.55),
    "Respiratory": (0.10, 0.00),
    "Rheumatology": (0.10, -0.10),
}
SITES = ["Riverside General", "Northgate Community Hospital", "St Anne's Treatment Centre"]
AGE_BANDS = [
    (0, 17, 0.10),
    (18, 29, 0.55),
    (30, 44, 0.25),
    (45, 64, 0.0),
    (65, 79, -0.35),
    (80, 99, -0.05),
]
WEEKDAY_EFFECT = [0.10, 0.0, -0.02, 0.0, 0.12]  # Mon..Fri
MONTH_EFFECT = {8: 0.10, 12: 0.18, 1: 0.05}
MODE_EFFECT = {"Face to face": 0.0, "Telephone": -0.45, "Video": -0.20}
TRIAL_EFFECT = -0.21  # log-odds effect of the "cost of a missed appointment" message
STATUS_VARIANTS = {
    "attended": ["Attended", "ATT", "attended", "Attended - seen"],
    "dna": ["DNA", "Did Not Attend", "dna", "D.N.A."],
    "patient_cancelled": ["Cancelled by patient", "CANC-PAT", "Patient cancelled"],
    "hospital_cancelled": ["Cancelled by hospital", "CANC-HOSP"],
}


@dataclass(frozen=True)
class GenerationSummary:
    patients: int
    clinics: int
    appointments: int
    trial_rows: int


def _age_effect(age: np.ndarray) -> np.ndarray:
    out = np.zeros(len(age))
    for lo, hi, eff in AGE_BANDS:
        out[(age >= lo) & (age <= hi)] = eff
    return out


def generate(
    data_dir: Path, n_patients: int = 60_000, n_appointments: int = 260_000, seed: int = 2024
) -> GenerationSummary:
    rng = np.random.default_rng(seed)
    data_dir.mkdir(parents=True, exist_ok=True)

    # --- patients ---------------------------------------------------------------------
    age = np.clip(np.round(rng.gamma(4.2, 12.5, n_patients)), 0, 99).astype(int)
    imd = rng.choice(
        np.arange(1, 11),
        n_patients,
        p=np.linspace(0.16, 0.05, 10) / np.linspace(0.16, 0.05, 10).sum(),
    )
    has_mobile = rng.random(n_patients) < np.where(age >= 80, 0.72, 0.94)
    propensity = rng.normal(0, 0.65, n_patients)
    patients = pd.DataFrame(
        {
            "patient_id": [f"P{100000 + i}" for i in range(n_patients)],
            "age": age,
            "sex": rng.choice(["F", "M"], n_patients, p=[0.54, 0.46]),
            "imd_decile": imd.astype(float),
            "distance_km": np.round(rng.lognormal(1.8, 0.7, n_patients), 1),
            "has_mobile": has_mobile,
        }
    )

    # --- clinics ----------------------------------------------------------------------
    clinic_rows = []
    for s_i, (spec, (share, _)) in enumerate(SPECIALTIES.items()):
        for site_i, site in enumerate(SITES):
            clinic_rows.append((f"C{s_i:02d}{site_i}", spec, site, share / len(SITES)))
    clinics = pd.DataFrame(clinic_rows, columns=["clinic_id", "specialty", "site", "w"])

    # --- appointments -----------------------------------------------------------------
    activity = rng.gamma(1.3, 1.0, n_patients)
    pidx = rng.choice(n_patients, n_appointments, p=activity / activity.sum())
    cidx = rng.choice(len(clinics), n_appointments, p=clinics["w"] / clinics["w"].sum())
    days = pd.bdate_range("2024-01-01", "2025-12-31")
    appt_day = pd.DatetimeIndex(rng.choice(days.values, n_appointments))
    slot_min = rng.integers(0, 17, n_appointments) * 30 + 8 * 60 + 30
    appt_dt = appt_day + pd.to_timedelta(slot_min, unit="m")
    new = rng.random(n_appointments) < 0.35
    lead = (
        np.where(
            new, rng.lognormal(3.7, 0.6, n_appointments), rng.lognormal(3.3, 0.8, n_appointments)
        )
        .round()
        .astype(int)
        + 1
    )
    mode = rng.choice(list(MODE_EFFECT), n_appointments, p=[0.80, 0.15, 0.05])

    spec = clinics["specialty"].to_numpy()[cidx]
    in_trial_window = (appt_day.date >= TRIAL_START) & (appt_day.date <= TRIAL_END)
    eligible = in_trial_window & has_mobile[pidx]
    arm = np.where(
        eligible, np.where(rng.random(n_appointments) < 0.5, "control", "cost_message"), None
    )

    logit = (
        -2.95
        + _age_effect(age[pidx])
        + (5.5 - imd[pidx]) * 0.09
        + 0.20 * (np.log1p(lead) - 3.5)
        + np.where(new, 0.12, 0.0)
        + np.array([MODE_EFFECT[m] for m in mode])
        + np.array([SPECIALTIES[s][1] for s in spec])
        + np.array(WEEKDAY_EFFECT)[appt_day.day_of_week.to_numpy()]
        + np.array([MONTH_EFFECT.get(m, 0.0) for m in appt_day.month])
        + 0.004 * patients["distance_km"].to_numpy()[pidx]
        + np.where(~has_mobile[pidx], 0.15, 0.0)
        + np.where(arm == "cost_message", TRIAL_EFFECT, 0.0)
        + propensity[pidx]
    )
    p_dna = 1 / (1 + np.exp(-logit))
    roll = rng.random(n_appointments)
    outcome = np.full(n_appointments, "attended", dtype=object)
    outcome[roll < 0.14] = "hospital_cancelled"
    outcome[roll < 0.08] = "patient_cancelled"
    dna = (roll >= 0.14) & (rng.random(n_appointments) < p_dna)
    outcome[dna] = "dna"
    status = np.array([rng.choice(STATUS_VARIANTS[o]) for o in outcome], dtype=object)

    booked = appt_day - pd.to_timedelta(lead, unit="D")
    appts = pd.DataFrame(
        {
            "appointment_id": [f"A{1_000_000 + i}" for i in range(n_appointments)],
            "patient_id": patients["patient_id"].to_numpy()[pidx],
            "clinic_id": clinics["clinic_id"].to_numpy()[cidx],
            "booked_date": booked.strftime("%Y-%m-%d"),
            "appointment_datetime": appt_dt.strftime("%Y-%m-%d %H:%M"),
            "appointment_type": np.where(new, "New", "Follow-up"),
            "contact_mode": mode,
            "attendance_status": status,
        }
    )

    # --- deliberate data-quality problems ---------------------------------------------
    bad_book = rng.random(n_appointments) < 0.002
    appts.loc[bad_book, "booked_date"] = (
        appt_day[bad_book] + pd.to_timedelta(rng.integers(1, 30, bad_book.sum()), unit="D")
    ).strftime("%Y-%m-%d")
    orphan = rng.random(n_appointments) < 0.001
    appts.loc[orphan, "clinic_id"] = "C999"
    dupes = appts.sample(frac=0.008, random_state=seed)
    appts = pd.concat([appts, dupes]).sort_values("appointment_datetime", kind="stable")
    bad_age = rng.random(n_patients) < 0.003
    patients.loc[bad_age, "age"] = rng.choice([-1, 150, 999], bad_age.sum())
    patients.loc[rng.random(n_patients) < 0.04, "imd_decile"] = np.nan

    trial = pd.DataFrame(
        {
            "appointment_id": [f"A{1_000_000 + i}" for i in np.flatnonzero(eligible)],
            "arm": arm[eligible],
            "sms_delivered": rng.random(int(eligible.sum())) < 0.965,
        }
    )

    patients.to_csv(data_dir / "patients.csv", index=False)
    clinics.drop(columns="w").to_csv(data_dir / "clinics.csv", index=False)
    appts.to_csv(data_dir / "appointments.csv", index=False)
    trial.to_csv(data_dir / "sms_trial.csv", index=False)
    return GenerationSummary(len(patients), len(clinics), len(appts), len(trial))


def ensure_data(data_dir: Path) -> None:
    if not (data_dir / "appointments.csv").exists():
        generate(data_dir)
