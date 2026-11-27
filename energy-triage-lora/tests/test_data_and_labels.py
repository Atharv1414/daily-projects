from collections import Counter

import pytest
from hypothesis import given
from hypothesis import strategies as st

from energy_triage_lora.data import (
    FAMILIES,
    HELD_OUT_FAMILIES,
    by_split,
    generate,
    read_jsonl,
    write_jsonl,
)
from energy_triage_lora.experiment import Data, check_no_leakage
from energy_triage_lora.labels import (
    CATEGORIES,
    FIELDS,
    LabelError,
    Triage,
    all_label_tokens,
    parse_tokens,
)

SMALL = {"train": 800, "val": 100, "test_seen": 100, "test_unseen": 200}


@pytest.fixture(scope="module")
def messages():
    return generate(7, SMALL)


def test_generation_is_reproducible(messages):
    again = generate(7, SMALL)
    assert [m.text for m in again] == [m.text for m in messages]
    assert [m.text for m in generate(8, SMALL)] != [m.text for m in messages]


def test_every_category_and_label_value_appears(messages):
    train = by_split(messages)["train"]
    assert {m.category for m in train} == set(CATEGORIES)
    for name, values in FIELDS:
        assert {getattr(m, name) for m in train} == set(values), name


def test_unseen_split_uses_only_held_out_families(messages):
    splits = by_split(messages)
    for m in splits["test_unseen"]:
        index = int(m.family.split("/")[1])
        assert index >= len(FAMILIES[m.category]) - HELD_OUT_FAMILIES
    check_no_leakage(Data(splits, "x"))


def test_unlabelled_traffic_covers_every_phrasing_but_is_never_labelled_training():
    msgs = generate(7, {"train": 200, "unlabelled": 600})
    splits = by_split(msgs)
    families = {m.family for m in splits["unlabelled"]}
    assert len(families) == sum(len(f) for f in FAMILIES.values())
    check_no_leakage(Data({**splits, "test_unseen": generate(7, {"test_unseen": 50})}, "x"))


def test_leakage_check_catches_a_held_out_family_in_training(messages):
    splits = by_split(messages)
    leaked = {**splits, "train": splits["train"] + splits["test_unseen"][:1]}
    with pytest.raises(AssertionError, match="leaked"):
        check_no_leakage(Data(leaked, "x"))


def test_vulnerable_customers_are_a_realistic_minority_and_raise_urgency(messages):
    train = by_split(messages)["train"]
    share = sum(m.vulnerable == "yes" for m in train) / len(train)
    assert 0.12 < share < 0.25
    faults = [m for m in train if m.category == "supply_fault" and m.vulnerable == "yes"]
    assert Counter(m.urgency for m in faults).most_common(1)[0][0] == "high"


def test_jsonl_round_trip(tmp_path, messages):
    path = tmp_path / "m.jsonl"
    write_jsonl(messages[:20], path)
    assert list(read_jsonl(path)) == messages[:20]


def test_triage_round_trips_through_text_and_tokens():
    t = Triage("supply_fault", "high", "yes")
    assert Triage.from_text(t.to_text()) == t
    assert parse_tokens(t.to_tokens()) == t
    assert len(all_label_tokens()) == sum(len(v) for _, v in FIELDS)


@pytest.mark.parametrize(
    "tokens",
    [
        ["<category:billing>", "<urgency:low>"],
        ["<category:billing>", "<category:billing>", "<vulnerable:no>"],
        ["<category:gas>", "<urgency:low>", "<vulnerable:no>"],
        ["hello", "<urgency:low>", "<vulnerable:no>"],
    ],
)
def test_malformed_model_output_is_rejected(tokens):
    with pytest.raises(LabelError):
        parse_tokens(tokens)


def test_invalid_labels_cannot_be_constructed():
    with pytest.raises(LabelError):
        Triage("billing", "critical", "no")
    with pytest.raises(LabelError):
        Triage.from_text("category=billing; urgency=low")


@given(
    st.sampled_from(CATEGORIES),
    st.sampled_from(["low", "medium", "high"]),
    st.sampled_from(["no", "yes"]),
)
def test_any_valid_triage_survives_the_token_round_trip(category, urgency, vulnerable):
    t = Triage(category, urgency, vulnerable)
    assert parse_tokens(t.to_tokens()) == t
