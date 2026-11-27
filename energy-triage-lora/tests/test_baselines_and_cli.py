import json

import pytest

from energy_triage_lora import cli
from energy_triage_lora.baselines import Keywords, Majority, TfidfLogistic
from energy_triage_lora.config import ExperimentConfig
from energy_triage_lora.data import by_split, generate
from energy_triage_lora.experiment import load_data, run_baselines
from energy_triage_lora.metrics import score
from energy_triage_lora.report import build, table

SIZES = {"train": 1200, "val": 200, "test_seen": 200, "test_unseen": 300}


@pytest.fixture(scope="module")
def splits():
    return by_split(generate(7, SIZES))


def test_keyword_rules_catch_the_obvious_cases():
    out = Keywords().predict(
        ["I can smell gas by the meter, URGENT", "Here is my meter reading 01234. No rush."]
    )
    assert out[0].category == "supply_fault" and out[0].urgency == "high"
    assert out[1].category == "meter_reading" and out[1].urgency == "low"
    assert Keywords().predict(["My mum is 87 and the power is off"])[0].vulnerable == "yes"
    # Written from seen phrasings only, so a held-out phrasing slips through.
    assert Keywords().predict(["We rely on a home dialysis machine."])[0].vulnerable == "no"


def test_tfidf_beats_majority_on_seen_phrasings(splits):
    test = splits["test_seen"]
    truth = [m.triage for m in test]
    texts = [m.text for m in test]
    tfidf = score(truth, TfidfLogistic().fit(splits["train"]).predict(texts))
    floor = score(truth, Majority().fit(splits["train"]).predict(texts))
    assert tfidf.exact_match > floor.exact_match + 0.3
    assert tfidf.category_accuracy > 0.9


def test_tfidf_confidence_is_a_probability(splits):
    model = TfidfLogistic().fit(splits["train"])
    conf = model.confidence([m.text for m in splits["val"]])
    assert ((conf > 0) & (conf <= 1)).all()


def test_baseline_results_have_every_split_and_an_abstention_policy():
    data = load_data(ExperimentConfig(), SIZES)
    results = run_baselines(data)
    assert set(results) == {"majority", "keyword rules", "TF-IDF + logistic regression"}
    tfidf = results["TF-IDF + logistic regression"]
    assert {"val", "test_seen", "test_unseen"} <= set(tfidf)
    ab = tfidf["abstention"]
    assert 0 < ab["test_seen"]["coverage"] <= 1
    assert ab["test_seen"]["accuracy_answered"] >= ab["test_seen"]["accuracy_all"]


def test_report_table_and_files_build_from_baseline_only_metrics(tmp_path):
    data = load_data(ExperimentConfig(), SIZES)
    metrics = {"baselines": run_baselines(data)}
    path = tmp_path / "metrics.json"
    path.write_text(json.dumps(metrics))
    made = build(path, tmp_path)
    assert (tmp_path / "results.md").exists() and len(made) == 1
    assert "| keyword rules |" in table(metrics)


def test_cli_data_command_writes_jsonl(tmp_path, capsys):
    out = tmp_path / "m.jsonl"
    assert cli.main(["data", "--out", str(out)]) == 0
    assert sum(1 for _ in out.open()) == 19_200
    assert "Wrote 19,200 messages" in capsys.readouterr().out


def test_cli_triage_answers_or_hands_over(capsys):
    assert (
        cli.main(["triage", "There is a smell of gas near the meter.", "--threshold", "0.5"]) == 0
    )
    out = capsys.readouterr().out
    assert "category=supply_fault" in out
