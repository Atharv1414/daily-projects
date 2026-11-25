import numpy as np
import pandas as pd
import pytest

from mortgage_exits import cleaning, datagen
from mortgage_exits.cleaning import CleaningLog, DataContractError
from mortgage_exits.config import Economics, Study


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("75", 75),
        ("75.0%", 75),
        ("0.75", 75),
        (" 60.5% ", 60.5),
        ("x", np.nan),
        (None, np.nan),
        ("400", np.nan),
    ],
)
def test_ltv_formats(text, value):
    got = cleaning.parse_ltv(pd.Series([text], dtype="object"))[0]
    assert got == pytest.approx(value, nan_ok=True)


@pytest.mark.parametrize(
    ("text", "value"), [("2025-03-01", "2025-03-01"), ("01/03/2025", "2025-03-01"), ("March", None)]
)
def test_dates_are_never_guessed(text, value):
    got = cleaning.parse_dates(pd.Series([text]))[0]
    assert pd.isna(got) if value is None else got == pd.Timestamp(value)


def test_month_numbers():
    start = pd.Series(pd.to_datetime(["2025-01-01"] * 3))
    end = pd.Series(pd.to_datetime(["2025-01-31", "2025-02-01", "2026-01-15"]))
    assert cleaning.months_between(start, end).tolist() == [1, 2, 13]


def test_payment_formula():
    # £200,000 over 25 years at 5% is £1,169.18 a month.
    got = datagen.monthly_payment(np.array([200_000]), np.array([5.0]), np.array([25]))[0]
    assert got == pytest.approx(1169.18, abs=0.01)


def events(*rows):
    return pd.DataFrame(rows, columns=["account_id", "event_date", "code", "status"])


def first(frame, study):
    log = CleaningLog()
    return cleaning.first_events(frame, pd.Series(["A", "B"]), study, log), log.frame()


def test_first_completed_event_wins(study):
    got, _ = first(
        events(
            ("A", "2025-01-05", "REDEMPTION:REMORTGAGE", "CANCELLED"),
            ("A", "2025-06-05", "ARREARS_90", "COMPLETED"),
            ("A", "2025-03-05", "PRODUCT_TRANSFER", "COMPLETED"),
        ),
        study,
    )
    assert got[["account_id", "cause"]].to_numpy().tolist() == [["A", 1]]


def test_repeats_orphans_and_future_events_are_dropped(study):
    row = ("A", "2025-03-05", "REDEMPTION:SALE", "COMPLETED")
    got, log = first(
        events(row, row, ("Z", *row[1:]), ("B", "2027-01-01", "ARREARS_90", "COMPLETED")), study
    )
    assert got["account_id"].tolist() == ["A"]
    counts = log.set_index("rule")["rows"]
    assert counts["Event repeated in the feed: dropped"] == 1
    assert counts["Event for an unknown account: dropped"] == 1


def test_unknown_code_stops_the_run(study):
    with pytest.raises(DataContractError, match="WIZARDRY"):
        first(events(("A", "2025-03-05", "WIZARDRY", "COMPLETED")), study)


def test_missing_column_stops_the_run(raw, study):
    broken = datagen.RawData(raw.accounts.drop(columns="ltv"), raw.events, raw.rates)
    with pytest.raises(DataContractError, match="ltv"):
        cleaning.build_study(broken, study)


def test_conflicting_rows_stop_the_run(raw, study):
    twin = raw.accounts.iloc[[0]].assign(balance=1)
    broken = datagen.RawData(pd.concat([raw.accounts, twin]), raw.events, raw.rates)
    with pytest.raises(DataContractError, match="share an account number"):
        cleaning.build_study(broken, study)


def test_study_table_is_sound(data, study):
    assert data["account_id"].is_unique
    assert (data["exit"] > data["entry"]).all() and data["exit"].le(study.max_month).all()
    assert data["cause"].isin(range(5)).all()
    assert data[["ltv", "age", "balance", "shock"]].notna().all().all()
    assert data["balance"].between(20_000, 1_200_000).all()
    assert set(data["region"]) == set(datagen.REGIONS)


def test_nobody_leaves_after_the_extract(data, study):
    left = data[data["cause"] > 0]
    assert (left["event_date"] <= study.extract).all()


def test_row_order_does_not_matter(study):
    """Shuffling the extract must not change a single outcome."""
    rng = np.random.default_rng(0)
    raw = datagen.generate(study)
    clean, _, _ = cleaning.build_study(raw, study)
    again = datagen.RawData(
        raw.accounts.sample(frac=1, random_state=int(rng.integers(99))), raw.events, raw.rates
    )
    other, _, _ = cleaning.build_study(again, study)
    key = ["account_id", "entry", "exit", "cause"]
    pd.testing.assert_frame_equal(
        clean[key].sort_values("account_id").reset_index(drop=True),
        other[key].sort_values("account_id").reset_index(drop=True),
    )


def test_same_seed_same_data(study):
    a, b = datagen.generate(study), datagen.generate(study)
    pd.testing.assert_frame_equal(a.accounts, b.accounts)
    pd.testing.assert_frame_equal(a.events, b.events)


@pytest.mark.parametrize(
    "bad", [{"accounts": 10}, {"horizon": 30}, {"split": pd.Timestamp("2030-01-01")}]
)
def test_impossible_studies_are_refused(bad):
    with pytest.raises(ValueError):
        Study(**bad)


def test_impossible_economics_are_refused():
    with pytest.raises(ValueError):
        Economics(save_rate=1.5)
