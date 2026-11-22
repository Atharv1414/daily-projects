from __future__ import annotations

import pytest
from pydantic import ValidationError

from fnol_business_case import process, requirements, risks
from fnol_business_case import stakeholders as sh


@pytest.fixture
def stories(data_dir):
    return requirements.load_backlog(data_dir / "backlog.json")


def test_backlog_loads_and_has_no_errors(stories):
    issues = requirements.validate_backlog(stories)
    assert not [i for i in issues if i.severity == "error"]
    assert all(s.acceptance for s in stories)


def test_story_validation_rejects_bad_points(stories):
    data = stories[0].model_dump()
    data["points"] = 4
    with pytest.raises(ValidationError):
        requirements.Story.model_validate(data)
    data["points"], data["acceptance"] = 5, []
    with pytest.raises(ValidationError):
        requirements.Story.model_validate(data)


def test_dependency_rules_and_cycles(stories):
    s = [x.model_copy() for x in stories]
    by = {x.id: x for x in s}
    by["FNOL-01"] = by["FNOL-01"].model_copy(update={"depends_on": ["FNOL-09"]})
    by["FNOL-04"] = by["FNOL-04"].model_copy(update={"depends_on": ["FNOL-01"]})
    issues = requirements.validate_backlog(list(by.values()))
    msgs = " ".join(i.message for i in issues)
    assert "cannot depend on a lower" in msgs and "cycle" in msgs


def test_prioritised_puts_dependencies_first(stories):
    order = [s.id for s in requirements.prioritised(stories)]
    for s in stories:
        for dep in s.depends_on:
            assert order.index(dep) < order.index(s.id)
    assert order[-1] == "FNOL-09"  # the Won't comes last


def test_gherkin_export(stories, tmp_path):
    paths = requirements.export_features(stories, tmp_path)
    assert len(paths) == sum(s.moscow != "Won't" for s in stories)
    text = paths[0].read_text()
    assert text.startswith("Feature:") and "Given" in text and "Then" in text and "And" in text


def test_wsjf():
    s = requirements.Story(
        id="FNOL-99",
        epic="e",
        as_a="a",
        i_want="b",
        so_that="c",
        moscow="Must",
        points=2,
        business_value=4,
        time_criticality=3,
        risk_reduction=1,
        acceptance=[{"scenario": "x x x", "given": ["g"], "when": ["w"], "then": ["t"]}],
    )
    assert s.cost_of_delay == 8 and s.wsjf == 4.0


def test_raci_rules(data_dir):
    people, raci = sh.load(data_dir / "stakeholders.json")
    findings = sh.analyse_raci(people, raci)
    assert not [f for f in findings if f.severity == "error"]
    assert any("no one is Responsible" in f.message for f in findings)
    bad = {
        **raci,
        "Broken": {"Claims Director": "A", "Chief Information Officer": "A", "Ghost": "X"},
    }
    errs = [f.message for f in sh.analyse_raci(people, bad) if f.severity == "error"]
    assert any("exactly one Accountable" in m for m in errs)
    assert any("unknown person" in m for m in errs) and any("invalid code" in m for m in errs)


@pytest.mark.parametrize(
    ("p", "i", "q"),
    [
        (5, 5, "Manage closely"),
        (5, 1, "Keep satisfied"),
        (1, 5, "Keep informed"),
        (1, 1, "Monitor"),
    ],
)
def test_quadrants(p, i, q):
    assert sh.Stakeholder("x", "r", p, i, "Neutral", "c").quadrant == q


def test_process_metrics_improve(data_dir):
    procs = process.load(data_dir / "processes.json")
    cur, fut = process.metrics(procs["current"]), process.metrics(procs["future"])
    assert fut.lead_time_hours < cur.lead_time_hours
    assert fut.process_cycle_efficiency > cur.process_cycle_efficiency
    assert fut.handoffs < cur.handoffs
    md = process.mermaid(procs["future"])
    assert md.startswith("flowchart LR") and "|simple|" in md and "subgraph" in md


def test_branch_probabilities_sum_to_one(data_dir):
    p = process.load(data_dir / "processes.json")["future"]
    assert sum(prob for _, prob in process._paths(p)) == pytest.approx(1.0)


def test_risks(data_dir):
    rs = risks.load(data_dir / "risks.json")
    assert all(r.residual_score <= r.score for r in rs)
    assert risks.rag(16) == "Red" and risks.rag(8) == "Amber" and risks.rag(4) == "Green"
    with pytest.raises(ValueError):
        risks.Risk("X", "r", "c", 6, 1, "o", "m", 1, 1)
    with pytest.raises(ValueError):
        risks.Risk("X", "r", "c", 1, 1, "o", "m", 2, 2)
    assert "reduction" in risks.to_markdown(rs)
