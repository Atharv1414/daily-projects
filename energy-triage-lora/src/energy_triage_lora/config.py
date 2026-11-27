"""Settings for the model and every training run.

Kept in one place so a run can be reproduced from its JSON.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ModelConfig:
    vocab_size: int = 0  # set from the tokenizer
    context: int = 112
    d_model: int = 128
    n_layer: int = 4
    n_head: int = 4
    dropout: float = 0.1


@dataclass(frozen=True)
class TrainConfig:
    steps: int
    lr: float
    batch_size: int = 64
    weight_decay: float = 0.05
    warmup: int = 50
    eval_every: int = 200


@dataclass(frozen=True)
class LoraConfig:
    rank: int = 8
    alpha: float = 16.0
    dropout: float = 0.05
    targets: tuple[str, ...] = ("q", "v")


@dataclass(frozen=True)
class ExperimentConfig:
    seed: int = 7
    max_text_tokens: int = 100
    bpe_merges: int = 700
    model: ModelConfig = field(default_factory=ModelConfig)
    pretrain: TrainConfig = field(default_factory=lambda: TrainConfig(steps=1000, lr=3e-3))
    full: TrainConfig = field(default_factory=lambda: TrainConfig(steps=400, lr=5e-4))
    lora: TrainConfig = field(default_factory=lambda: TrainConfig(steps=400, lr=3e-3))
    head: TrainConfig = field(default_factory=lambda: TrainConfig(steps=400, lr=3e-3))
    lora_adapter: LoraConfig = field(default_factory=LoraConfig)
    abstain_target: float = 0.97
    threads: int = int(os.environ.get("TRIAGE_THREADS", "4"))

    def as_dict(self) -> dict:
        return asdict(self)


def quick() -> ExperimentConfig:
    """A tiny run for tests: same code paths, seconds instead of minutes."""
    return ExperimentConfig(
        model=ModelConfig(context=80, d_model=32, n_layer=1, n_head=2, dropout=0.0),
        bpe_merges=120,
        max_text_tokens=70,
        pretrain=TrainConfig(steps=40, lr=3e-3, batch_size=32, warmup=5, eval_every=20),
        full=TrainConfig(steps=30, lr=1e-3, batch_size=32, warmup=5, eval_every=15),
        lora=TrainConfig(steps=30, lr=5e-3, batch_size=32, warmup=5, eval_every=15),
        head=TrainConfig(steps=30, lr=5e-3, batch_size=32, warmup=5, eval_every=15),
        lora_adapter=LoraConfig(rank=4, alpha=8.0),
    )
