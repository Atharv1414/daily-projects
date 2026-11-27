"""A small decoder-only transformer built from a config, and LoRA adapters for it.

No weights are downloaded: everything is trained from scratch here.

Pre-norm blocks, causal self-attention, learned positions and tied input/output embeddings: the same
shape as GPT-2, about a thousandth of the size.
"""

from __future__ import annotations

import math

import torch
from torch import nn
from torch.nn import functional as F

from .config import LoraConfig, ModelConfig


class LoRALinear(nn.Module):
    """y = W x + (alpha / r) * B A x, with W frozen.

    B starts at zero, so training starts from exactly the base model.
    """

    def __init__(self, base: nn.Linear, rank: int, alpha: float, dropout: float) -> None:
        super().__init__()
        self.base = base
        for p in self.base.parameters():
            p.requires_grad_(False)
        self.rank = rank
        self.scale = alpha / rank
        self.A = nn.Parameter(torch.empty(rank, base.in_features))
        self.B = nn.Parameter(torch.zeros(base.out_features, rank))
        nn.init.kaiming_uniform_(self.A, a=math.sqrt(5))
        self.dropout = nn.Dropout(dropout)
        self.merged = False

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.base(x)
        if self.merged:
            return out
        return out + self.dropout(x) @ self.A.T @ self.B.T * self.scale

    @torch.no_grad()
    def merge(self) -> None:
        """Folds the adapter into W, so inference costs exactly what the base model costs."""
        if not self.merged:
            self.base.weight += (self.B @ self.A) * self.scale
            self.merged = True


class Attention(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        if cfg.d_model % cfg.n_head:
            raise ValueError("d_model must divide evenly between heads")
        self.n_head = cfg.n_head
        self.q = nn.Linear(cfg.d_model, cfg.d_model)
        self.k = nn.Linear(cfg.d_model, cfg.d_model)
        self.v = nn.Linear(cfg.d_model, cfg.d_model)
        self.o = nn.Linear(cfg.d_model, cfg.d_model)
        self.dropout = cfg.dropout

    def forward(self, x: torch.Tensor, pad_mask: torch.Tensor | None) -> torch.Tensor:
        b, t, d = x.shape
        h = self.n_head

        def heads(z: torch.Tensor) -> torch.Tensor:
            return z.view(b, t, h, d // h).transpose(1, 2)

        q, k, v = heads(self.q(x)), heads(self.k(x)), heads(self.v(x))
        mask = torch.ones(t, t, dtype=torch.bool, device=x.device).tril()
        if pad_mask is not None:
            mask = mask & pad_mask[:, None, None, :]
        y = F.scaled_dot_product_attention(
            q, k, v, attn_mask=mask, dropout_p=self.dropout if self.training else 0.0
        )
        return self.o(y.transpose(1, 2).reshape(b, t, d))


class Block(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.ln1 = nn.LayerNorm(cfg.d_model)
        self.attn = Attention(cfg)
        self.ln2 = nn.LayerNorm(cfg.d_model)
        self.mlp = nn.Sequential(
            nn.Linear(cfg.d_model, 4 * cfg.d_model),
            nn.GELU(),
            nn.Linear(4 * cfg.d_model, cfg.d_model),
            nn.Dropout(cfg.dropout),
        )

    def forward(self, x: torch.Tensor, pad_mask: torch.Tensor | None) -> torch.Tensor:
        x = x + self.attn(self.ln1(x), pad_mask)
        return x + self.mlp(self.ln2(x))


class TinyGPT(nn.Module):
    def __init__(self, cfg: ModelConfig) -> None:
        super().__init__()
        self.cfg = cfg
        self.tok = nn.Embedding(cfg.vocab_size, cfg.d_model)
        self.pos = nn.Embedding(cfg.context, cfg.d_model)
        self.drop = nn.Dropout(cfg.dropout)
        self.blocks = nn.ModuleList(Block(cfg) for _ in range(cfg.n_layer))
        self.ln = nn.LayerNorm(cfg.d_model)
        self.apply(self._init)

    @staticmethod
    def _init(module: nn.Module) -> None:
        if isinstance(module, nn.Linear):
            nn.init.normal_(module.weight, std=0.02)
            nn.init.zeros_(module.bias)
        elif isinstance(module, nn.Embedding):
            nn.init.normal_(module.weight, std=0.02)

    def forward(self, ids: torch.Tensor, pad_mask: torch.Tensor | None = None) -> torch.Tensor:
        t = ids.shape[1]
        if t > self.cfg.context:
            raise ValueError(
                f"sequence of {t} tokens is longer than the context of {self.cfg.context}"
            )
        x = self.drop(self.tok(ids) + self.pos(torch.arange(t, device=ids.device)))
        for block in self.blocks:
            x = block(x, pad_mask)
        # Tied output head: the same matrix reads tokens in and scores them out.
        return self.ln(x) @ self.tok.weight.T


def count_parameters(model: nn.Module, trainable_only: bool = False) -> int:
    return sum(p.numel() for p in model.parameters() if p.requires_grad or not trainable_only)


def add_lora(model: TinyGPT, cfg: LoraConfig) -> list[LoRALinear]:
    """Freezes the model and wraps the chosen attention projections with adapters."""
    for p in model.parameters():
        p.requires_grad_(False)
    adapters = []
    for block in model.blocks:
        for name in cfg.targets:
            wrapped = LoRALinear(getattr(block.attn, name), cfg.rank, cfg.alpha, cfg.dropout)
            setattr(block.attn, name, wrapped)
            adapters.append(wrapped)
    return adapters


def train_label_rows(model: TinyGPT, label_ids: list[int]) -> torch.Tensor:
    """Lets only the label tokens' embedding rows learn.

    Pre-training never saw the label tokens, so their rows are random. Every fine-tuning method
    here trains those rows (the equivalent of new tokens in "modules to save") and nothing else in
    the embedding. A gradient hook zeroes every other row.
    """
    weight = model.tok.weight
    weight.requires_grad_(True)
    keep = torch.zeros(weight.shape[0], 1)
    keep[label_ids] = 1.0
    weight.register_hook(lambda grad: grad * keep)
    return keep


def adapter_state(model: TinyGPT, label_ids: list[int]) -> dict[str, torch.Tensor]:
    """What you would ship per task: the LoRA matrices plus the label rows."""
    state = {
        name: p.detach().clone()
        for name, p in model.named_parameters()
        if name.endswith((".A", ".B"))
    }
    state["label_rows"] = model.tok.weight.detach()[label_ids].clone()
    return state
