"""Model tests. They need torch (an optional extra) and train for seconds, not minutes."""

import copy

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from energy_triage_lora.config import LoraConfig, ModelConfig, quick  # noqa: E402
from energy_triage_lora.data import by_split, generate  # noqa: E402
from energy_triage_lora.experiment import run  # noqa: E402
from energy_triage_lora.labels import FIELDS, label_token  # noqa: E402
from energy_triage_lora.model import LoRALinear, TinyGPT, add_lora, count_parameters  # noqa: E402
from energy_triage_lora.tokenizer import Tokenizer  # noqa: E402
from energy_triage_lora.train import encode, finetune, predict, task_batch  # noqa: E402

CFG = ModelConfig(vocab_size=300, context=40, d_model=32, n_layer=2, n_head=4, dropout=0.0)


def test_model_is_causal_so_later_tokens_cannot_change_earlier_logits():
    torch.manual_seed(0)
    model = TinyGPT(CFG).eval()
    a = torch.randint(0, 300, (1, 12))
    b = a.clone()
    b[0, 8:] = torch.randint(0, 300, (4,))
    assert torch.allclose(model(a)[0, :8], model(b)[0, :8], atol=1e-5)


def test_right_padding_does_not_change_real_positions():
    torch.manual_seed(0)
    model = TinyGPT(CFG).eval()
    ids = torch.randint(1, 300, (1, 10))
    padded = torch.cat([ids, torch.zeros(1, 5, dtype=torch.long)], dim=1)
    mask = padded != 0
    assert torch.allclose(model(ids)[0], model(padded, mask)[0, :10], atol=1e-5)


def test_context_limit_is_enforced():
    with pytest.raises(ValueError, match="context"):
        TinyGPT(CFG)(torch.zeros(1, 41, dtype=torch.long))


def test_lora_starts_as_the_base_model_and_trains_only_adapters():
    torch.manual_seed(0)
    model = TinyGPT(CFG).eval()
    x = torch.randint(0, 300, (2, 9))
    before = model(x)
    adapters = add_lora(model, LoraConfig(rank=4, alpha=8.0, dropout=0.0))
    assert len(adapters) == CFG.n_layer * 2
    assert torch.allclose(before, model(x), atol=1e-6)
    trainable = count_parameters(model, trainable_only=True)
    assert trainable == CFG.n_layer * 2 * (4 * 32 + 32 * 4)


def test_merging_an_adapter_gives_the_same_output():
    torch.manual_seed(0)
    layer = LoRALinear(torch.nn.Linear(16, 8), rank=2, alpha=4.0, dropout=0.0)
    with torch.no_grad():
        layer.B.normal_()
    x = torch.randn(3, 16)
    unmerged = layer(x)
    layer.merge()
    assert torch.allclose(unmerged, layer(x), atol=1e-5)


def test_task_batch_scores_only_the_answer():
    # Second prompt is two tokens shorter, so it ends in padding after the one-token shift.
    ids, targets, mask = task_batch(
        [[1, 5, 6, 2], [1, 2]], [[10, 11, 12, 3], [13, 14, 15, 3]], pad=0
    )
    assert ids.shape == (2, 7)
    assert (targets[0] != -100).sum() == 4
    assert targets[0, :3].tolist() == [-100, -100, -100]
    assert targets[1, 1:5].tolist() == [13, 14, 15, 3]
    assert targets[1, 5:].tolist() == [-100, -100]
    assert mask[1, :6].all() and not mask[1, 6]


@pytest.fixture(scope="module")
def tiny_setup():
    torch.manual_seed(0)
    splits = by_split(generate(5, {"train": 300, "test_seen": 40}))
    tok = Tokenizer.train([m.text for m in splits["train"]], num_merges=80)
    model = TinyGPT(
        ModelConfig(vocab_size=tok.size, context=80, d_model=32, n_layer=1, n_head=2, dropout=0.0)
    )
    return splits, tok, model


def test_head_only_fine_tuning_changes_only_label_rows(tiny_setup):
    splits, tok, base = tiny_setup
    model = copy.deepcopy(base)
    before = {k: v.clone() for k, v in model.state_dict().items()}
    data = encode(splits["train"], tok, 60)
    cfg = quick().head
    run_log = finetune(model, data, "head", cfg, tok, seed=1)
    labels = [tok.id(label_token(n, v)) for n, vals in FIELDS for v in vals]
    after = model.state_dict()
    changed = [k for k in before if not torch.equal(before[k], after[k])]
    assert changed == ["tok.weight"]
    diff_rows = (
        (before["tok.weight"] != after["tok.weight"]).any(dim=1).nonzero().flatten().tolist()
    )
    assert set(diff_rows) <= set(labels)
    assert run_log.trainable == len(labels) * 32


def test_constrained_decoding_is_always_valid(tiny_setup):
    splits, tok, model = tiny_setup
    prompts = encode(splits["test_seen"], tok, 60).prompts
    constrained = predict(model, prompts, tok, constrained=True)
    assert all(p.triage is not None for p in constrained)
    assert all(0 < p.confidence <= 1 for p in constrained)
    free = predict(model, prompts, tok, constrained=False)
    assert len(free) == len(
        prompts
    )  # an untrained model mostly produces junk, which is reported, not crashed on


def test_unknown_fine_tuning_method_is_refused(tiny_setup):
    splits, tok, base = tiny_setup
    with pytest.raises(ValueError, match="unknown method"):
        finetune(
            copy.deepcopy(base),
            encode(splits["train"][:5], tok, 60),
            "prefix",
            quick().head,
            tok,
            seed=1,
        )


@pytest.mark.slow
def test_whole_experiment_runs_and_reports_every_method(tmp_path):
    metrics = run(
        quick(),
        tmp_path,
        sizes={"train": 400, "val": 100, "test_seen": 100, "test_unseen": 100, "unlabelled": 200},
    )
    methods = metrics["transformer"]["methods"]
    assert set(methods) == {"head", "lora", "full"}
    assert (
        methods["head"]["trainable_parameters"]
        < methods["lora"]["trainable_parameters"]
        < methods["full"]["trainable_parameters"]
    )
    assert methods["lora"]["merge_agreement"] == 1.0
    assert set(metrics["transformer"]["without_unlabelled"]) == {"lora", "full"}
    assert metrics["transformer"]["pretrain"]["unlabelled_texts"] > 0
    q = metrics["transformer"]["quantized_lora"]
    assert q["int8_bytes"] < q["float32_bytes"] / 3
    assert (tmp_path / "lora_adapter.npz").exists() and (tmp_path / "metrics.json").exists()
    assert np.isfinite(methods["full"]["test_unseen"]["exact_match"])
