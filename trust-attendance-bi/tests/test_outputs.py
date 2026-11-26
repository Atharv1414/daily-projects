import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from trust_attendance_bi.charts import render
from trust_attendance_bi.dashboard import build as build_dashboard
from trust_attendance_bi.disclosure import round_counts, suppress
from trust_attendance_bi.semantic import MetricQuery


def _table(counts):
    return pd.DataFrame(
        [
            {"school": s, "group": g, "pupils": n, "rate": 90.0 + n / 10}
            for (s, g), n in counts.items()
        ]
    )


def test_primary_suppression_hides_small_groups_but_not_zero():
    df = suppress(_table({("A", "x"): 3, ("A", "y"): 0, ("A", "z"): 40}), ["school", "group"])
    hidden = df.set_index("group").suppressed
    assert hidden["x"] and not hidden["y"]
    assert df.loc[df.group == "x", "rate"].item() == "c"


def test_secondary_suppression_protects_the_single_hidden_cell():
    counts = {("A", "x"): 2, ("A", "y"): 30, ("A", "z"): 50, ("B", "x"): 20, ("B", "y"): 25}
    df = suppress(_table(counts), ["school", "group"]).set_index(["school", "group"])
    assert df.loc[("A", "x"), "suppressed"]
    assert df.loc[("A", "y"), "suppressed"]  # next smallest in school A
    assert not df.loc[("A", "z"), "suppressed"]
    # Group "x" across schools now has one hidden cell too, so B/x is suppressed as well.
    assert df.loc[("B", "x"), "suppressed"]


@given(
    st.dictionaries(
        st.tuples(st.sampled_from("ABCD"), st.sampled_from("wxyz")),
        st.integers(min_value=0, max_value=40),
        min_size=2,
    )
)
def test_no_group_ever_has_exactly_one_hidden_cell(counts):
    df = suppress(_table(counts), ["school", "group"])
    published = df[~df.suppressed]
    assert not ((published.pupils != "c") & published.pupils.between(1, 4)).any()
    for dim in ("school", "group"):
        for _, rows in df.groupby(dim):
            if len(rows) > 1:
                assert rows.suppressed.sum() != 1


def test_round_counts_to_nearest_five():
    assert round_counts(pd.Series([0, 2, 3, 7, 13, "c"])).tolist() == [0, 0, 5, 5, 15, "c"]
    with pytest.raises(ValueError):
        suppress(pd.DataFrame({"school": ["A"]}), ["school"])


def test_dashboard_pages_reconcile_and_respect_security(sl, con, tmp_path):
    pages = build_dashboard(sl, tmp_path)
    names = {p.name for p in pages}
    assert {"index.html", "groups.html", "quality.html", "school-S01.html"} <= names
    rate = con.execute(
        "SELECT round(100.0 * sum(present) / sum(possible), 1) FROM fact_attendance_session"
    ).fetchone()[0]
    assert f"<b>{rate:.1f}%</b>" in (tmp_path / "index.html").read_text()
    s01 = (tmp_path / "school-S01.html").read_text()
    assert "Wrenfield" in s01
    assert "(head teacher view)" in s01
    assert "<td class='c'>c</td>" in (tmp_path / "groups.html").read_text()


def test_head_page_numbers_come_only_from_their_school(sl):
    from trust_attendance_bi.semantic import Principal

    mine, _ = sl.query(MetricQuery(["pupils"]), Principal("head", "S02"))
    everyone, _ = sl.query(MetricQuery(["pupils"], ["school"]))
    assert mine.pupils.iloc[0] == everyone.set_index("school").pupils["S02"]


def test_charts_render(sl, tmp_path):
    paths = render(sl, tmp_path)
    assert len(paths) == 6
    assert all(p.stat().st_size > 10_000 for p in paths)
