"""Constants and paths for the analysis."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# NHS England's commonly cited cost of a missed outpatient appointment (2024/25 terms).
COST_PER_DNA_GBP = 160.0
# Marginal cost of one SMS reminder sent through NHS Notify (approximate, per message).
COST_PER_SMS_GBP = 0.02
# Cost of a targeted phone call reminder by an admin team member (about 4 minutes, Band 3).
COST_PER_CALL_GBP = 1.60

TRIAL_START = date(2025, 4, 1)
TRIAL_END = date(2025, 9, 30)
ALPHA = 0.05


@dataclass(frozen=True)
class Paths:
    data_dir: Path
    figures_dir: Path
    reports_dir: Path

    @classmethod
    def from_env(cls) -> Paths:
        return cls(
            data_dir=Path(os.environ.get("DNA_DATA_DIR", PROJECT_ROOT / "data")),
            figures_dir=Path(os.environ.get("DNA_FIGURES_DIR", PROJECT_ROOT / "docs" / "figures")),
            reports_dir=Path(os.environ.get("DNA_REPORTS_DIR", PROJECT_ROOT / "reports")),
        )
