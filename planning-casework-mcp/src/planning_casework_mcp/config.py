"""Settings, all overridable from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Settings:
    db_path: str = "data/casework.db"
    seed_size: int = 3000
    today: date = date(2026, 11, 27)  # fixed "today" so every run gives the same answers
    model: str = "claude-sonnet-5-5"
    max_steps: int = 12
    max_tool_calls: int = 20
    max_tokens_per_call: int = 16000
    # USD per million tokens for the default model, used only for the cost estimate.
    input_price_per_mtok: float = 2.0
    output_price_per_mtok: float = 10.0

    @classmethod
    def from_env(cls) -> Settings:
        base = cls()
        return cls(
            db_path=os.environ.get("PLANNING_DB", base.db_path),
            seed_size=int(os.environ.get("PLANNING_SEED_SIZE", base.seed_size)),
            today=date.fromisoformat(os.environ.get("PLANNING_TODAY", base.today.isoformat())),
            model=os.environ.get("AGENT_MODEL", base.model),
            max_steps=int(os.environ.get("AGENT_MAX_STEPS", base.max_steps)),
            max_tool_calls=int(os.environ.get("AGENT_MAX_TOOL_CALLS", base.max_tool_calls)),
        )
