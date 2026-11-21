import pandas as pd

from outpatient_dna.cleaning import STATUS_MAP, age_band
from outpatient_dna.segments import high_risk_profile, rate_table, specialty_imd_matrix


def test_cleaning_removes_known_problems(raw, dataset):
    a = dataset.appointments
    assert a["appointment_id"].is_unique
    assert set(a["status"]) == set(STATUS_MAP.values())
    assert (a["lead_days"] >= 0).all()
    assert a["specialty"].notna().all()  # orphan clinic codes dropped
    assert a["age"].dropna().between(0, 110).all()
    assert len(a) < len(raw["appointments"])


def test_cleaning_log_accounts_for_rows(raw, dataset):
    steps = {s: n for s, n, _ in dataset.log.steps}
    removed = (
        steps["Exact duplicate rows removed"]
        + steps["Duplicate appointment IDs removed"]
        + steps["Unmapped status removed"]
        + steps["Booked after appointment removed"]
        + steps["Unknown clinic codes removed"]
    )
    assert steps["Raw appointment rows"] - removed == steps["Clean appointment rows"]
    assert "| Step |" in dataset.log.to_markdown()


def test_prior_dnas_use_only_earlier_appointments(dataset):
    a = dataset.appointments.sort_values(["patient_id", "appointment_datetime"])
    first = a.groupby("patient_id").head(1)
    assert (first["prior_dnas"] == 0).all()
    one = a[a["patient_id"] == a["patient_id"].value_counts().index[0]]
    expected = (one["dna"].cumsum() - one["dna"]).clip(upper=3).tolist()
    assert one["prior_dnas"].tolist() == expected


def test_attendable_excludes_cancellations(dataset):
    assert set(dataset.attendable["status"]) == {"attended", "dna"}


def test_age_band_edges():
    bands = age_band(pd.Series([0, 17, 18, 29, 30, 79, 80, None]))
    assert bands.tolist()[:7] == ["0-17", "0-17", "18-29", "18-29", "30-44", "65-79", "80+"]
    assert pd.isna(bands.iloc[7])


def test_rate_table_counts_and_cis(dataset):
    t = rate_table(dataset.attendable, "specialty")
    assert t["appointments"].sum() == len(dataset.attendable)
    assert ((t["ci_low"] <= t["dna_rate"]) & (t["dna_rate"] <= t["ci_high"])).all()


def test_high_risk_profile_shares(dataset):
    t = high_risk_profile(dataset.attendable)
    assert abs(t["share_of_dnas"].sum() - 1) < 1e-9
    assert t["dna_rate"].is_monotonic_decreasing


def test_deprivation_gradient_present(dataset):
    m = specialty_imd_matrix(dataset.attendable)
    assert (m[1] > m[5]).mean() >= 0.8  # most specialties: Q1 above Q5
