"""Pre-training, the three fine-tuning methods, and constrained decoding."""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass, field, replace

import numpy as np
import torch
from torch.nn import functional as F

from .config import ExperimentConfig, LoraConfig, TrainConfig
from .data import Message
from .labels import FIELDS, LabelError, Triage, label_token, parse_tokens
from .model import TinyGPT, add_lora, count_parameters, train_label_rows
from .tokenizer import Tokenizer

log = logging.getLogger(__name__)

IGNORE = -100


def seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


@dataclass
class Encoded:
    """Token ids for each message: the prompt (<bos> text <sep>) and the answer tokens."""

    prompts: list[list[int]]
    answers: list[list[int]]


def encode(messages: list[Message], tok: Tokenizer, max_text_tokens: int) -> Encoded:
    prompts, answers = [], []
    for m in messages:
        text = tok.encode(m.text)[:max_text_tokens]
        prompts.append([tok.id("<bos>"), *text, tok.id("<sep>")])
        answers.append([tok.id(t) for t in m.triage.to_tokens()] + [tok.id("<eos>")])
    return Encoded(prompts, answers)


def _pad(rows: list[list[int]], value: int) -> torch.Tensor:
    width = max(len(r) for r in rows)
    return torch.tensor([r + [value] * (width - len(r)) for r in rows], dtype=torch.long)


def lm_batch(
    texts: list[list[int]], tok: Tokenizer
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Next-token prediction on raw text: <bos> text <eos>."""
    seqs = [[tok.id("<bos>"), *t, tok.id("<eos>")] for t in texts]
    ids = _pad(seqs, tok.id("<pad>"))
    targets = ids.clone()
    targets[ids == tok.id("<pad>")] = IGNORE
    return ids[:, :-1], targets[:, 1:], (ids != tok.id("<pad>"))[:, :-1]


def task_batch(
    prompts: list[list[int]], answers: list[list[int]], pad: int
) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
    """Prompt then answer; the loss counts only the answer tokens."""
    seqs = [p + a for p, a in zip(prompts, answers, strict=True)]
    ids = _pad(seqs, pad)
    targets = torch.full_like(ids, IGNORE)
    for i, (p, a) in enumerate(zip(prompts, answers, strict=True)):
        targets[i, len(p) : len(p) + len(a)] = torch.tensor(a)
    return ids[:, :-1], targets[:, 1:], (ids != pad)[:, :-1]


def _optimizer(model: torch.nn.Module, cfg: TrainConfig) -> torch.optim.Optimizer:
    decay, no_decay = [], []
    for name, p in model.named_parameters():
        if not p.requires_grad:
            continue
        # Embeddings, norms and biases are not decayed. For LoRA runs that also keeps
        # weight decay off the frozen embedding rows.
        (no_decay if p.ndim < 2 or name.startswith(("tok", "pos")) else decay).append(p)
    return torch.optim.AdamW(
        [
            {"params": decay, "weight_decay": cfg.weight_decay},
            {"params": no_decay, "weight_decay": 0.0},
        ],
        lr=cfg.lr,
        betas=(0.9, 0.98),
    )


def _lr_at(step: int, cfg: TrainConfig) -> float:
    if step < cfg.warmup:
        return cfg.lr * (step + 1) / cfg.warmup
    progress = (step - cfg.warmup) / max(1, cfg.steps - cfg.warmup)
    return cfg.lr * (0.1 + 0.9 * 0.5 * (1 + math.cos(math.pi * progress)))


@dataclass
class RunLog:
    name: str
    seconds: float = 0.0
    trainable: int = 0
    total: int = 0
    curve: list[tuple[int, float]] = field(default_factory=list)


def _loop(model, cfg: TrainConfig, sample, name: str, rng: random.Random) -> RunLog:
    opt = _optimizer(model, cfg)
    run = RunLog(
        name, trainable=count_parameters(model, trainable_only=True), total=count_parameters(model)
    )
    started = time.perf_counter()
    model.train()
    smoothed = None
    for step in range(cfg.steps):
        for group in opt.param_groups:
            group["lr"] = _lr_at(step, cfg)
        x, y, mask = sample(rng, cfg.batch_size)
        logits = model(x, mask)
        loss = F.cross_entropy(
            logits.reshape(-1, logits.shape[-1]), y.reshape(-1), ignore_index=IGNORE
        )
        opt.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad], 1.0)
        opt.step()
        smoothed = loss.item() if smoothed is None else 0.95 * smoothed + 0.05 * loss.item()
        if (step + 1) % cfg.eval_every == 0 or step == cfg.steps - 1:
            run.curve.append((step + 1, round(smoothed, 4)))
            log.info("%s step %d loss %.3f", name, step + 1, smoothed)
    run.seconds = round(time.perf_counter() - started, 2)
    model.eval()
    return run


def pretrain(
    texts: list[list[int]], model: TinyGPT, cfg: TrainConfig, tok: Tokenizer, seed: int
) -> RunLog:
    """Language modelling on unlabelled messages.

    The model learns how customers write before it learns the task.
    """

    def sample(rng: random.Random, n: int):
        return lm_batch([texts[rng.randrange(len(texts))] for _ in range(n)], tok)

    return _loop(model, cfg, sample, "pretrain", random.Random(seed))


def finetune(
    model: TinyGPT,
    data: Encoded,
    method: str,
    cfg: TrainConfig,
    tok: Tokenizer,
    seed: int,
    lora: LoraConfig | None = None,
) -> RunLog:
    """Fine-tune with one of three methods.

    "full" trains every weight, "lora" trains adapters on attention plus the label rows,
    and "head" trains the label rows only.
    """
    label_ids = [tok.id(label_token(name, v)) for name, values in FIELDS for v in values]
    if method == "lora":
        add_lora(model, lora or LoraConfig())
        train_label_rows(model, label_ids)
    elif method == "head":
        for p in model.parameters():
            p.requires_grad_(False)
        train_label_rows(model, label_ids)
    elif method != "full":
        raise ValueError(f"unknown method {method!r}")
    pad = tok.id("<pad>")

    def sample(rng: random.Random, n: int):
        idx = [rng.randrange(len(data.prompts)) for _ in range(n)]
        return task_batch([data.prompts[i] for i in idx], [data.answers[i] for i in idx], pad)

    run = _loop(model, cfg, sample, method, random.Random(seed))
    if method != "full":
        # The whole embedding matrix has requires_grad set, but the hook lets only the
        # label rows change.
        embedding = model.tok.weight
        run.trainable = run.trainable - embedding.numel() + len(label_ids) * embedding.shape[1]
    return run


@dataclass(frozen=True)
class Prediction:
    triage: Triage | None  # None when unconstrained output did not fit the schema
    confidence: float
    tokens: tuple[str, ...]


@torch.no_grad()
def predict(
    model: TinyGPT,
    prompts: list[list[int]],
    tok: Tokenizer,
    constrained: bool = True,
    batch: int = 256,
) -> list[Prediction]:
    """Greedy decoding of the three label slots.

    Constrained decoding only lets slot k choose among field k's label tokens, so every answer is
    valid by construction; confidence is the product of the three renormalised probabilities.
    Unconstrained decoding takes the argmax over the whole vocabulary, which shows how often the
    model would produce something unusable on its own.
    """
    model.eval()
    allowed = [
        torch.tensor([tok.id(label_token(name, v)) for v in values]) for name, values in FIELDS
    ]
    pad = tok.id("<pad>")
    out: list[Prediction] = []
    for start in range(0, len(prompts), batch):
        chunk = prompts[start : start + batch]
        seqs = [list(p) for p in chunk]
        conf = torch.ones(len(chunk))
        for slot in range(len(FIELDS)):
            ids = _pad(seqs, pad)
            logits = model(ids, ids != pad)
            last = torch.tensor([len(s) - 1 for s in seqs])
            step = logits[torch.arange(len(seqs)), last]
            if constrained:
                probs = F.softmax(step[:, allowed[slot]], dim=-1)
                best = probs.argmax(dim=-1)
                chosen = allowed[slot][best]
                conf *= probs.max(dim=-1).values
            else:
                probs = F.softmax(step, dim=-1)
                chosen = probs.argmax(dim=-1)
                conf *= probs.max(dim=-1).values
            for s, c in zip(seqs, chosen.tolist(), strict=True):
                s.append(c)
        for s, p, c in zip(seqs, chunk, conf.tolist(), strict=True):
            tokens = tuple(tok.token(i) for i in s[len(p) :])
            try:
                triage = parse_tokens(list(tokens))
            except LabelError:
                triage = None
            out.append(Prediction(triage, float(c), tokens))
    return out


def build_model(cfg: ExperimentConfig, vocab_size: int) -> TinyGPT:
    return TinyGPT(replace(cfg.model, vocab_size=vocab_size))
