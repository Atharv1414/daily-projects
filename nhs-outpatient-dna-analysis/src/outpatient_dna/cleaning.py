"""Load the PAS extract and clean it, recording every step in a cleaning log."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

STATUS_MAP = {
    "attended": "attended",
    "att": "attended",
    "attended - seen": "attended",
    "dna": "dna",
    "did not attend": "dna",
    "d.n.a.": "dna",
    "cancelled by patient": "patient_cancelled",
    "canc-pat": "patient_cancelled",
    "patient cancelled": "patient_cancelled",
    "cancelled by hospital": "hospital_cancelled",
    "canc-hosp": "hospital_cancelled",
}
AGE_BANDS = [
    (0, 17, "0-17"),
    (18, 29, "18-29"),
    (30, 44, "30-44"),
    (45, 64, "45-64"),
    (65, 79, "65-79"),
    (80, 120, "80+"),
]
LEAD_BANDS = [0, 14, 28, 56, 112, 10_000]
LEAD_LABELS = ["0-13 d", "14-27 d", "28-55 d", "56-111 d", "112+ d"]


@dataclass
class CleaningLog:
    steps: list[tuple[str, int, str]] = field(default_factory=list)

    def add(self, step: str, rows_affected: int, note: str = "") -> None:
        self.steps.append((step, int(rows_affected), note))

    def to_markdown(self) -> str:
        lines = ["| Step | Rows affected | Note |", "|---|---:|---|"]
        lines += [f"| {s} | {n:,} | {note} |" for s, n, note in self.steps]
        return "\n".join(lines)


@dataclass
class Dataset:
    appointments: pd.DataFrame  # one row per valid appointment, enriched
    trial: pd.DataFrame
    log: CleaningLog

    @property
    def attendable(self) -> pd.DataFrame:
        """Appointments that went ahead (attended or DNA): the DNA-rate denominator."""
        return self.appointments[self.appointments["status"].isin(["attended", "dna"])]


def load_raw(data_dir: Path) -> dict[str, pd.DataFrame]:
    return {
        name: pd.read_csv(data_dir / f"{name}.csv")
        for name in ("patients", "clinics", "appointments", "sms_trial")
    }


def age_band(age: pd.Series) -> pd.Series:
    out = pd.Series(pd.NA, index=age.index, dtype="object")
    for lo, hi, label in AGE_BANDS:
        out[(age >= lo) & (age <= hi)] = label
    return out


def clean(raw: dict[str, pd.DataFrame]) -> Dataset:
    log = CleaningLog()
    patients = raw["patients"].copy()
    appts = raw["appointments"].copy()
    log.add("Raw appointment rows", len(appts))

    before = len(appts)
    appts = appts.drop_duplicates()
    log.add("Exact duplicate rows removed", before - len(appts), "system sync re-sent rows")
    before = len(appts)
    appts = appts.drop_duplicates("appointment_id", keep="last")
    log.add("Duplicate appointment IDs removed", before - len(appts), "kept latest")

    raw_status = appts["attendance_status"].astype(str).str.strip().str.lower()
    appts["status"] = raw_status.map(STATUS_MAP)
    log.add(
        "Status labels standardised",
        int((raw_status != appts["status"]).sum()),
        f"{raw['appointments']['attendance_status'].nunique()} labels -> 4 categories",
    )
    unknown = appts["status"].isna()
    log.add("Unmapped status removed", int(unknown.sum()))
    appts = appts[~unknown]

    appts["appointment_datetime"] = pd.to_datetime(appts["appointment_datetime"])
    appts["booked_date"] = pd.to_datetime(appts["booked_date"])
    appts["lead_days"] = (
        appts["appointment_datetime"].dt.normalize() - appts["booked_date"]
    ).dt.days
    bad_lead = appts["lead_days"] < 0
    log.add("Booked after appointment removed", int(bad_lead.sum()), "PAS data-entry error")
    appts = appts[~bad_lead]

    clinics = raw["clinics"]
    orphan = ~appts["clinic_id"].isin(clinics["clinic_id"])
    log.add("Unknown clinic codes removed", int(orphan.sum()), "orphan foreign key")
    appts = appts[~orphan].merge(clinics, on="clinic_id", how="left")

    invalid_age = ~patients["age"].between(0, 110)
    log.add("Impossible ages set to missing", int(invalid_age.sum()), "e.g. -1, 150, 999")
    patients.loc[invalid_age, "age"] = np.nan
    log.add(
        "Missing IMD decile (kept, own category)",
        int(patients["imd_decile"].isna().sum()),
        "postcode not matched",
    )
    appts = appts.merge(patients, on="patient_id", how="left", validate="many_to_one")

    appts = appts.sort_values(["patient_id", "appointment_datetime"]).reset_index(drop=True)
    is_dna = (appts["status"] == "dna").astype(int)
    appts["prior_dnas"] = (is_dna.groupby(appts["patient_id"]).cumsum() - is_dna).clip(upper=3)
    appts["prior_appts"] = appts.groupby("patient_id").cumcount()
    appts["dna"] = is_dna
    appts["age_band"] = age_band(appts["age"])
    appts["imd_group"] = (
        appts["imd_decile"].map(lambda d: "Unknown" if pd.isna(d) else f"{int(d)}").astype(str)
    )
    appts["lead_band"] = pd.cut(appts["lead_days"], LEAD_BANDS, right=False, labels=LEAD_LABELS)
    appts["weekday"] = appts["appointment_datetime"].dt.day_name().str[:3]
    appts["week"] = appts["appointment_datetime"].dt.to_period("W-SUN").dt.start_time
    appts["month"] = appts["appointment_datetime"].dt.to_period("M").astype(str)

    trial = (
        raw["sms_trial"]
        .drop_duplicates("appointment_id")
        .merge(
            appts[["appointment_id", "status", "dna", "specialty", "age_band", "imd_group"]],
            on="appointment_id",
            how="inner",
        )
    )
    log.add("Trial allocations matched to clean appointments", len(trial))
    log.add("Clean appointment rows", len(appts))
    return Dataset(appts, trial, log)
