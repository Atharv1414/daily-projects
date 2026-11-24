from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from damp_mould_repairs_business_case import cli, content, pipeline, report
from damp_mould_repairs_business_case.finance import (
    Assumptions,
    Option,
    break_even_breach_cost,
    cash_flows,
    irr,
    npv,
    option_npv,
    payback_years,
    tornado,
)

DIGITAL = Option("d", breaches_avoided=1500, digital=True)


@pytest.fixture(scope="module")
def analysis():
    return pipeline.run(replications=3)


def test_npv_known_value():
    assert npv([-100, 60, 60], 0.10) == pytest.approx(4.132, abs=0.001)


def test_irr_known_value():
    assert irr([-100, 60, 60]) == pytest.approx(0.1307, abs=0.0001)


@given(st.floats(1e3, 1e6), st.lists(st.floats(1, 1e6), min_size=1, max_size=8))
def test_irr_makes_npv_zero(cost, inflows):
    flows = [-cost, *inflows]
    rate = irr(flows)
    if rate is not None:
        assert abs(npv(flows, rate)) < 1e-3 * cost


@pytest.mark.parametrize("flows", [[-100, -5, -5], [0, 10, 10], [50, -10]])
def test_irr_is_none_when_undefined(flows):
    assert irr(flows) is None


@pytest.mark.parametrize(
    ("flows", "years"), [([-100, 50, 50], 2.0), ([-100, 0, 200], 1.5), ([-100, 10, 10], None)]
)
def test_payback(flows, years):
    assert payback_years(flows) == years


def test_cash_flows_by_hand():
    a = Assumptions()
    flows = cash_flows(DIGITAL, a)
    assert flows[0] == pytest.approx(-230_000 * 1.2)
    assert flows[1] == pytest.approx(1500 * 410 * 0.5 - 80_000)
    assert flows[2] == pytest.approx(1500 * 410 - 80_000)
    assert len(flows) == 6


def test_staff_options_have_no_one_off_cost():
    flows = cash_flows(Option("h", 0, 2, 2, 1), Assumptions())
    assert flows == [0, *[-(104_000 + 196_000 + 33_000)] * 5]


def test_break_even_gives_zero_npv():
    a = Assumptions()
    cost = break_even_breach_cost(DIGITAL, a)
    scaled = replace(a, claim_rate=0.0, goodwill=cost)
    assert option_npv(DIGITAL, scaled) == pytest.approx(0, abs=1)
    assert break_even_breach_cost(replace(DIGITAL, breaches_avoided=0), a) is None


def test_tornado_is_sorted_and_brackets_the_base():
    a = Assumptions()
    swings = tornado(DIGITAL, a)
    assert [s.width for s in swings] == sorted((s.width for s in swings), reverse=True)
    base = option_npv(DIGITAL, a)
    assert all(min(s.low, s.high) < base < max(s.low, s.high) for s in swings)
    assert "crew_cost" not in {s.assumption for s in swings}  # no effect on this option


def test_content_is_valid():
    loaded = content.load()
    assert len(loaded.stories) >= 12
    assert {s.priority for s in loaded.stories} == set(content.PRIORITIES)


def broken(**changes):
    return content.validate(replace(content.load(), **changes))


def test_content_rules_catch_mistakes():
    good = content.load()
    first = good.stories[0]
    assert "duplicate" in broken(stories=(*good.stories, first))[0]
    assert "does not trace" in " ".join(broken(stories=(replace(first, solves=("PP99",)),)))
    assert "PP3: no in-scope story" in " ".join(
        broken(stories=tuple(s for s in good.stories if "PP3" not in s.solves))
    )
    musts = tuple(replace(s, priority="Must") for s in good.stories)
    assert "of effort" in " ".join(broken(stories=musts))
    assert "unknown priority" in " ".join(
        broken(stories=(*good.stories[1:], replace(first, priority="Maybe")))
    )


@pytest.mark.parametrize(
    ("codes", "message"),
    [
        (("A", "A", "R", "", "", "", ""), "exactly one"),
        (("A", "C", "C", "", "", "", ""), "nobody is responsible"),
        (("A", "R"), "wrong number"),
        (("A", "R", "X", "", "", "", ""), "unknown code"),
    ],
)
def test_raci_rules(codes, message):
    assert message in " ".join(broken(raci={"Do it": codes}))


def test_load_raises_on_invalid_text():
    folder = Path(content.__file__).parent / "content"
    text = (folder / "analysis.toml").read_text().replace("impact = 5", "impact = 9")
    with pytest.raises(content.ContentError, match="scores must be"):
        content.load(text)


def test_model_reproduces_the_log(analysis):
    seen = analysis.observed()
    assert analysis.mean(pipeline.BASE, "met_investigate").mean == pytest.approx(
        seen["met_investigate"], abs=0.05
    )
    assert analysis.mean(pipeline.BASE, "no_access_visits").mean == pytest.approx(
        seen["no_access_visits"], rel=0.10
    )
    assert analysis.mean(pipeline.BASE, "mean_days").mean == pytest.approx(
        seen["mean_days"], rel=0.5
    )


def test_recommended_option_beats_doing_nothing(analysis):
    assert analysis.change(pipeline.RECOMMENDED, "breached_cases").high < 0
    options, a = analysis.options, analysis.assumptions
    assert option_npv(options[pipeline.RECOMMENDED], a) > 0
    best = max(options, key=lambda n: option_npv(options[n], a))
    assert best == pipeline.RECOMMENDED


def test_stress_test_is_harder_than_today(analysis):
    for name, runs in analysis.stressed.items():
        assert sum(runs["mean_days"]) > sum(analysis.runs[name]["mean_days"])


def test_every_modelled_story_has_a_verdict(analysis):
    for story in analysis.content.in_scope:
        value, met = analysis.story_result(story)
        assert (value is None) == (met is None)
    wont = next(s for s in analysis.content.stories if s.priority == "Won't")
    assert analysis.story_result(wont) == (None, None)


def test_report_is_complete(analysis, tmp_path):
    paths = report.write_all(analysis, tmp_path)
    assert len(paths) == 9
    text = (tmp_path / "BUSINESS_CASE.md").read_text()
    for heading in ("Executive summary", "Current state", "Options", "RACI", "Risks"):
        assert f"## {heading}" in text
    assert not re.search(r"\bnan\b", text.lower())
    matrix = (tmp_path / "REQUIREMENTS.md").read_text()
    assert all(s.id in matrix for s in analysis.content.stories)
    feature = (tmp_path / "acceptance.feature").read_text()
    assert feature.count("Scenario:") == len(analysis.content.in_scope)


def test_cli(tmp_path, capsys):
    path = tmp_path / "log.csv"
    assert cli.main(["extract", "--out", str(path)]) == 0
    assert cli.main(["mine", "--log", str(path)]) == 0
    assert "fully conforming" in capsys.readouterr().out
    assert cli.main(["what-if", "--crews", "20", "--deadline-queue"]) == 0
    assert cli.main(["what-if", "--crews", "0"]) == 1
    assert cli.main(["mine", "--log", str(tmp_path / "none.csv")]) == 1
    with pytest.raises(SystemExit):
        cli.main(["options", "--replications", "1"])
