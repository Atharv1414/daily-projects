import math

from outpatient_dna.analysis import analyse_trial, headline, run
from outpatient_dna.cli import main
from outpatient_dna.config import Paths
from outpatient_dna.datagen import TRIAL_EFFECT
from outpatient_dna.report import build


def test_trial_recovers_true_effect(dataset):
    t = analyse_trial(dataset.trial)
    base = t.itt.control_rate
    odds = base / (1 - base) * math.exp(TRIAL_EFFECT)
    true_rr = odds / (1 + odds) / base
    assert t.itt.rr_ci[0] < true_rr < t.itt.rr_ci[1]
    assert t.srm_p > 0.01
    assert set(t.arms["arm"]) == {"control", "cost_message"}


def test_full_run_writes_findings_and_figures(data_dir, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DNA_DATA_DIR", str(data_dir))
    monkeypatch.setenv("DNA_FIGURES_DIR", str(tmp_path / "fig"))
    monkeypatch.setenv("DNA_REPORTS_DIR", str(tmp_path / "rep"))
    assert main(["run"]) == 0
    out = capsys.readouterr().out
    assert "SMS trial" in out and "9 figures" in out
    findings = (tmp_path / "rep" / "FINDINGS.md").read_text()
    for section in (
        "Executive summary",
        "SMS reminder trial",
        "What drives DNA risk",
        "Forecasting",
        "Financial case",
        "Caveats",
    ):
        assert section in findings
    assert len(list((tmp_path / "fig").glob("*.png"))) == 9


def test_headline_numbers_are_consistent(data_dir, tmp_path):
    paths = Paths(data_dir, tmp_path / "f", tmp_path / "r")
    results = run(paths, make_figures=False)
    h = headline(results)
    assert 0.04 < h["dna_rate"] < 0.12
    assert h["cost_2025"] == h["dnas_2025"] * 160
    assert h["trial_treatment"] < h["trial_control"]
    assert "£" in build(results)
