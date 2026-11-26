import pandas as pd
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from trust_attendance_bi.semantic import (
    TABLES,
    AccessDenied,
    MetricQuery,
    Principal,
    QueryError,
)


@pytest.mark.parametrize(
    ("metrics", "by", "expected"),
    [
        (["attendance_rate"], ["school", "term"], "agg_group_term"),
        (["attendance_rate"], ["school", "month"], "agg_group_month"),
        (["absence_rate"], ["phase", "week"], "agg_group_week"),
        (["persistent_absence_rate"], ["school"], "agg_pupil_term"),
        (["pupils"], ["year_group", "fsm"], "agg_pupil_term"),
        (["pupils"], ["week"], "fact_attendance_session"),
        (["sessions_missed"], ["code"], "fact_attendance_session"),
        (["attendance_rate"], ["weekday"], "fact_attendance_session"),
    ],
)
def test_navigator_picks_the_smallest_table_that_is_correct(sl, metrics, by, expected):
    assert sl.choose(MetricQuery(metrics, by))[0].name == expected


@pytest.mark.parametrize("by", [["school"], ["phase", "term"], ["year_group", "sex", "fsm"], []])
def test_every_capable_table_gives_the_same_answer(sl, by):
    query = MetricQuery(["attendance_rate", "unauthorised_absence_rate", "sessions_possible"], by)
    answers = [sl.query(query, table_name=t.name)[0] for t in TABLES if set(by) <= t.dims]
    assert len(answers) >= 4
    for other in answers[1:]:
        pd.testing.assert_frame_equal(answers[0], other, check_dtype=False)


def test_persistent_absence_matches_a_pupil_by_pupil_count(sl, con):
    df, _ = sl.query(MetricQuery(["persistent_absence_rate", "pupils"], ["phase"]))
    raw = con.execute(
        """
        SELECT phase, count(*) AS pupils,
               round(100.0 * avg(((a) >= 0.1 * p)::INTEGER), 2) AS pa
        FROM (SELECT pupil_id, phase, sum(possible) p, sum(authorised + unauthorised) a
              FROM fact_attendance_session GROUP BY ALL)
        GROUP BY phase ORDER BY phase
        """
    ).df()
    assert list(df.pupils) == list(raw.pupils)
    assert list(df.persistent_absence_rate) == list(raw.pa)


def test_pupil_metrics_are_not_summed_across_terms(sl):
    by_term, _ = sl.query(MetricQuery(["pupils"], ["term"]))
    year, _ = sl.query(MetricQuery(["pupils"]))
    assert by_term.pupils.sum() > year.pupils.iloc[0]  # most pupils are in all three terms


def test_head_teacher_only_sees_their_school(sl):
    head = Principal.parse("head:S03")
    df, plan = sl.query(MetricQuery(["attendance_rate"], ["school"]), head)
    assert list(df.school) == ["S03"]
    assert "S03" in plan.params
    with pytest.raises(AccessDenied):
        sl.query(MetricQuery(["attendance_rate"], [], {"school": "S05"}), head)
    with pytest.raises(AccessDenied):
        sl.query(MetricQuery(["attendance_rate"], [], {"school": ["S03", "S05"]}), head)


def test_year_lead_is_scoped_to_one_year_group(sl):
    lead = Principal.parse("year_lead:S06:9")
    df, _ = sl.query(MetricQuery(["pupils"], ["school", "year_group"]), lead)
    assert df[["school", "year_group"]].values.tolist() == [["S06", "9"]]


@pytest.mark.parametrize("text", ["head", "head:S01:x", "boss", "year_lead:S01"])
def test_bad_roles_are_rejected(text):
    with pytest.raises(QueryError):
        Principal.parse(text)


@pytest.mark.parametrize(
    "query",
    [
        MetricQuery([], ["school"]),
        MetricQuery(["happiness"], ["school"]),
        MetricQuery(["attendance_rate"], ["postcode"]),
        MetricQuery(["attendance_rate"], ["school", "school"]),
        MetricQuery(["attendance_rate"], [], {"school": []}),
    ],
)
def test_invalid_queries_fail_clearly(sl, query):
    with pytest.raises(QueryError):
        sl.query(query)


def test_filter_values_are_parameters_not_sql(sl):
    df, plan = sl.query(MetricQuery(["pupils"], [], {"school": "S01' OR '1'='1"}))
    assert "OR '1'='1" not in plan.sql
    assert df.pupils.iloc[0] == 0


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    schools=st.lists(
        st.sampled_from([f"S0{i}" for i in range(1, 9)]), min_size=1, max_size=4, unique=True
    ),
    term=st.sampled_from(["Autumn", "Spring", "Summer"]),
    fsm=st.booleans(),
)
def test_aggregate_and_fact_agree_for_any_filter(sl, schools, term, fsm):
    query = MetricQuery(
        ["attendance_rate", "sessions_missed"],
        ["school"],
        {"school": schools, "term": term, "fsm": fsm},
    )
    fast, plan = sl.query(query)
    slow, _ = sl.query(query, table_name="fact_attendance_session")
    assert plan.table == "agg_group_term"
    pd.testing.assert_frame_equal(fast, slow, check_dtype=False)
