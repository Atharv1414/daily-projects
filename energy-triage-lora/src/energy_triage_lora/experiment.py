"""The whole experiment, end to end: data, tokenizer, baselines, pre-training, three fine-tunes,
merging, int8 quantisation, abstention, and a metrics file that the report is built from."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .baselines import Keywords, Majority, TfidfLogistic
from .config import ExperimentConfig
from .data import Message, by_split, generate
from .metrics import coverage_curve, expected_calibration_error, score, threshold_for
from .quantize import quantize_state
from .tokenizer import Tokenizer

log = logging.getLogger(__name__)

EVAL_SPLITS = ("val", "test_seen", "test_unseen")


@dataclass
class Data:
    splits: dict[str, list[Message]]
    fingerprint: str

    def texts(self, split: str) -> list[str]:
        return [m.text for m in self.splits.get(split, [])]

    def truth(self, split: str):
        return [m.triage for m in self.splits[split]]


def load_data(cfg: ExperimentConfig, sizes: dict[str, int] | None = None) -> Data:
    messages = generate(cfg.seed, sizes)
    digest = hashlib.sha256(
        "\n".join(f"{m.text}\t{m.triage.to_text()}" for m in messages).encode()
    ).hexdigest()[:16]
    return Data(by_split(messages), digest)


def check_no_leakage(data: Data) -> None:
    """Held-out phrasing families must not appear anywhere the models learn from."""
    learn = {m.family for split in ("train", "val") for m in data.splits.get(split, [])}
    unseen = {m.family for m in data.splits["test_unseen"]}
    overlap = learn & unseen
    if overlap:
        raise AssertionError(f"held-out families leaked into training: {sorted(overlap)}")


def run_baselines(data: Data) -> dict:
    results = {}
    train = data.splits["train"]
    for model in (Majority(), Keywords(), TfidfLogistic()):
        started = time.perf_counter()
        model.fit(train)
        entry = {"fit_seconds": round(time.perf_counter() - started, 2)}
        for split in EVAL_SPLITS:
            entry[split] = score(data.truth(split), model.predict(data.texts(split))).as_dict()
        if isinstance(model, TfidfLogistic):
            entry["abstention"] = _abstention(
                {s: model.confidence(data.texts(s)) for s in EVAL_SPLITS},
                {
                    s: [
                        p == t
                        for p, t in zip(model.predict(data.texts(s)), data.truth(s), strict=True)
                    ]
                    for s in EVAL_SPLITS
                },
                target=0.97,
            )
        results[model.name] = entry
        log.info("baseline %s done", model.name)
    return results


def _abstention(confidence: dict, correct: dict, target: float) -> dict:
    """Pick the threshold on validation; report what it does on the test sets, unchanged."""
    threshold = threshold_for(confidence["val"], correct["val"], target)
    out = {"target": target, "threshold": round(threshold, 4)}
    for split in ("test_seen", "test_unseen"):
        conf = np.asarray(confidence[split])
        hit = np.asarray(correct[split], dtype=bool)
        answered = conf >= threshold
        out[split] = {
            "coverage": round(float(answered.mean()), 4),
            "accuracy_answered": round(float(hit[answered].mean()) if answered.any() else 1.0, 4),
            "accuracy_all": round(float(hit.mean()), 4),
            "ece": round(expected_calibration_error(conf, hit), 4),
        }
    return out


def run_transformers(data: Data, cfg: ExperimentConfig, out_dir: Path) -> dict:
    """Needs torch. Imported here so the rest of the package works without it."""
    import torch

    from .model import adapter_state
    from .train import Encoded, build_model, encode, finetune, predict, pretrain, seed_everything

    torch.set_num_threads(cfg.threads)
    seed_everything(cfg.seed)
    labelled_text = data.texts("train") + data.texts("val")
    # Unlabelled traffic may contain held-out phrasings, but never a test message itself.
    test_texts = set(data.texts("test_seen")) | set(data.texts("test_unseen"))
    unlabelled = [t for t in data.texts("unlabelled") if t not in test_texts]
    tok = Tokenizer.train(labelled_text + unlabelled, cfg.bpe_merges)
    out_dir.mkdir(parents=True, exist_ok=True)
    tok.save(out_dir / "tokenizer.json")
    encoded = {
        s: encode(data.splits[s], tok, cfg.max_text_tokens) for s in EVAL_SPLITS + ("train",)
    }
    lengths = [len(p) for p in encoded["train"].prompts]

    def pretrained(texts: list[str]):
        seed_everything(cfg.seed)
        model = build_model(cfg, tok.size)
        ids = [tok.encode(t)[: cfg.max_text_tokens] for t in texts]
        return model, pretrain(ids, model, cfg.pretrain, tok, cfg.seed)

    base, pre = pretrained(labelled_text + unlabelled)
    base_labelled_only, pre_labelled_only = pretrained(labelled_text)
    results: dict = {
        "tokenizer": {
            "vocab": tok.size,
            "merges": len(tok.merges),
            "mean_prompt_tokens": round(float(np.mean(lengths)), 1),
        },
        "pretrain": {
            "seconds": pre.seconds,
            "parameters": pre.total,
            "curve": pre.curve,
            "texts": len(labelled_text) + len(unlabelled),
            "unlabelled_texts": len(unlabelled),
            "unlabelled_dropped_as_test_duplicates": len(data.texts("unlabelled"))
            - len(unlabelled),
            "labelled_only_seconds": pre_labelled_only.seconds,
        },
        "methods": {},
        "without_unlabelled": {},
    }

    def evaluate(model, name: str) -> dict:
        entry: dict = {}
        confidence, correct = {}, {}
        for split in EVAL_SPLITS:
            preds = predict(model, encoded[split].prompts, tok, constrained=True)
            entry[split] = score(data.truth(split), [p.triage for p in preds]).as_dict()
            confidence[split] = [p.confidence for p in preds]
            correct[split] = [p.triage == t for p, t in zip(preds, data.truth(split), strict=True)]
        free = predict(model, encoded["test_unseen"].prompts, tok, constrained=False)
        entry["unconstrained_valid_rate"] = round(
            sum(p.triage is not None for p in free) / len(free), 4
        )
        entry["abstention"] = _abstention(confidence, correct, cfg.abstain_target)
        entry["coverage_curve_unseen"] = [
            (round(t, 4), round(c, 4), round(a, 4))
            for t, c, a in coverage_curve(confidence["test_unseen"], correct["test_unseen"])[::25]
        ]
        log.info("%s unseen exact match %.3f", name, entry["test_unseen"]["exact_match"])
        return entry

    label_ids = [tok.id(t) for t in tok.special_ids if t.startswith("<") and ":" in t]
    plan = [(m, base, "methods") for m in ("head", "lora", "full")]
    plan += [(m, base_labelled_only, "without_unlabelled") for m in ("lora", "full")]
    for method, start, group in plan:
        seed_everything(cfg.seed)
        model = copy.deepcopy(start)
        train_cfg = getattr(cfg, method)
        run = finetune(
            model,
            Encoded(encoded["train"].prompts, encoded["train"].answers),
            method,
            train_cfg,
            tok,
            cfg.seed,
            cfg.lora_adapter,
        )
        entry = {
            "seconds": run.seconds,
            "trainable_parameters": run.trainable,
            "total_parameters": run.total,
            "curve": run.curve,
        }
        entry.update(evaluate(model, f"{method} ({group})"))
        if method == "lora" and group == "methods":
            state = adapter_state(model, label_ids)
            arrays = {k.replace(".", "_"): v.numpy() for k, v in state.items()}
            np.savez_compressed(out_dir / "lora_adapter.npz", **arrays)
            entry["adapter_bytes"] = int(sum(a.nbytes for a in arrays.values()))
            before = predict(model, encoded["test_unseen"].prompts, tok)
            for module in model.modules():
                if hasattr(module, "merge"):
                    module.merge()
            after = predict(model, encoded["test_unseen"].prompts, tok)
            entry["merge_agreement"] = round(
                sum(a.triage == b.triage for a, b in zip(before, after, strict=True)) / len(after),
                4,
            )
            results["quantized_lora"] = _quantized(model, encoded, data, tok, predict)
        results[group][method] = entry
    results["base_parameters_bytes"] = int(sum(p.numel() * 4 for p in base.parameters()))
    return results


def _quantized(model, encoded, data: Data, tok: Tokenizer, predict) -> dict:
    import torch

    q = copy.deepcopy(model)
    state = {k: v.detach().numpy() for k, v in q.state_dict().items()}
    deq, sizes = quantize_state(state)
    q.load_state_dict({k: torch.from_numpy(np.ascontiguousarray(v)) for k, v in deq.items()})
    entry: dict = dict(sizes)
    for split in ("test_seen", "test_unseen"):
        preds = predict(q, encoded[split].prompts, tok)
        entry[split] = score(data.truth(split), [p.triage for p in preds]).as_dict()
    return entry


def run(
    cfg: ExperimentConfig,
    out_dir: Path,
    sizes: dict[str, int] | None = None,
    with_torch: bool = True,
) -> dict:
    started = time.perf_counter()
    data = load_data(cfg, sizes)
    check_no_leakage(data)
    results = {
        "config": cfg.as_dict(),
        "data": {
            "fingerprint": data.fingerprint,
            "sizes": {s: len(v) for s, v in data.splits.items()},
            "vulnerable_share_train": round(
                float(np.mean([m.vulnerable == "yes" for m in data.splits["train"]])), 4
            ),
        },
        "baselines": run_baselines(data),
    }
    if with_torch:
        results["transformer"] = run_transformers(data, cfg, out_dir)
    results["wall_seconds"] = round(time.perf_counter() - started, 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    return results
