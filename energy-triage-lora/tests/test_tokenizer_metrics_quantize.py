import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from energy_triage_lora.data import generate
from energy_triage_lora.labels import Triage
from energy_triage_lora.metrics import (
    coverage_curve,
    expected_calibration_error,
    macro_f1,
    score,
    threshold_for,
)
from energy_triage_lora.quantize import quantize, quantize_state
from energy_triage_lora.tokenizer import SPECIALS, Tokenizer


@pytest.fixture(scope="module")
def tok():
    texts = [m.text for m in generate(3, {"train": 400})]
    return Tokenizer.train(texts, num_merges=200)


def test_bpe_learns_merges_that_shorten_text(tok):
    text = "My smart meter has stopped sending readings since March."
    ids = tok.encode(text)
    assert len(ids) < len(text.encode()) / 2
    assert tok.decode(ids) == text


@settings(max_examples=60, deadline=None)
@given(st.text(max_size=80))
def test_any_text_round_trips_even_unseen_characters(tok, text):
    assert tok.decode(tok.encode(text)) == text


def test_digits_stay_single_so_account_numbers_do_not_bloat_the_vocabulary(tok):
    pieces = [tok.token(i) for i in tok.encode("FE-48213907")]
    assert all(len(p.strip()) <= 1 for p in pieces if p.strip().isdigit())


def test_specials_have_fixed_ids_and_save_load_round_trip(tok, tmp_path):
    assert tok.id("<pad>") == 0
    assert tok.token(tok.id("<category:billing>")) == "<category:billing>"
    assert tok.size == len(SPECIALS) + 256 + len(tok.merges)
    tok.save(tmp_path / "tok.json")
    again = Tokenizer.load(tmp_path / "tok.json")
    assert again.encode("Power cut in Saltmarsh") == tok.encode("Power cut in Saltmarsh")


def test_scores_reward_exact_matches_and_track_vulnerable_recall():
    truth = [
        Triage("billing", "low", "no"),
        Triage("supply_fault", "high", "yes"),
        Triage("tariff", "low", "yes"),
    ]
    pred = [
        Triage("billing", "low", "no"),
        Triage("supply_fault", "medium", "yes"),
        Triage("tariff", "low", "no"),
    ]
    s = score(truth, pred)
    assert s.exact_match == pytest.approx(1 / 3)
    assert s.category_accuracy == 1.0
    assert s.vulnerable_recall == 0.5
    assert s.high_urgency_recall == 0.0
    with pytest.raises(ValueError):
        score(truth, pred[:2])


def test_macro_f1_weights_classes_equally():
    truth = ["a"] * 9 + ["b"]
    assert macro_f1(truth, ["a"] * 10, ["a", "b"]) == pytest.approx((2 * 9 / 19 + 0) / 2)


def test_calibration_error_is_zero_when_confidence_matches_accuracy():
    conf = [0.75] * 4
    assert expected_calibration_error(conf, [True, True, True, False]) == pytest.approx(0.0)
    assert expected_calibration_error([1.0, 1.0], [False, False]) == pytest.approx(1.0)


def test_threshold_keeps_only_answers_confident_enough_to_hit_the_target():
    conf = [0.99, 0.95, 0.9, 0.6, 0.5]
    right = [True, True, True, False, True]
    curve = coverage_curve(conf, right)
    assert curve[2] == (0.9, 0.6, 1.0)
    assert threshold_for(conf, right, 0.95) == 0.9
    assert threshold_for(conf, right, 0.5) == 0.5
    assert threshold_for([0.5], [False], 0.9) == 1.0


def test_int8_quantisation_is_close_and_four_times_smaller():
    rng = np.random.default_rng(0)
    w = rng.normal(0, 0.05, size=(64, 128)).astype(np.float32)
    w[3] *= 20  # one loud row must not ruin the others
    q = quantize(w)
    assert q.values.dtype == np.int8
    err = np.abs(q.dequantize() - w)
    assert (err <= q.scales[:, None] / 2 + 1e-7).all()
    assert np.abs(q.dequantize()[0] - w[0]).max() < 0.002
    deq, sizes = quantize_state({"w": w, "bias": np.zeros(64, np.float32)})
    assert sizes["int8_bytes"] < sizes["float32_bytes"] / 3.5
    assert deq["bias"].dtype == np.float32


def test_quantise_rejects_non_matrices_and_handles_zero_rows():
    with pytest.raises(ValueError):
        quantize(np.zeros(3))
    assert (quantize(np.zeros((2, 4))).dequantize() == 0).all()
