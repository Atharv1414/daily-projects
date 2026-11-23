"""Streaming anomaly detection on rebuffering ratio per (CDN, region).

Each key keeps an exponentially weighted mean and variance of its own rebuffering ratio
(EWMA/EWMVar). A window alerts when its ratio is ``z_threshold`` standard deviations above
that key's baseline **and** above an absolute floor **and** has enough watch time to matter.
Only windows that look normal (``z < guard_z``) are folded into the baseline. Suspicious and
alerting windows are kept out, so the slow ramp into an incident cannot drag the baseline up
until the incident looks normal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(slots=True)
class Baseline:
    mean: float = 0.0
    var: float = 0.0
    n: int = 0

    def update(self, x: float, alpha: float) -> None:
        if self.n == 0:
            self.mean, self.var = x, 0.0
        else:
            diff = x - self.mean
            incr = alpha * diff
            self.mean += incr
            self.var = (1 - alpha) * (self.var + diff * incr)
        self.n += 1


class RebufferAlertDetector:
    def __init__(
        self,
        z_threshold: float,
        min_ratio: float,
        min_watch_ms: int,
        warmup: int,
        alpha: float,
        guard_z: float = 2.0,
        min_std: float = 0.002,
    ) -> None:
        self.z_threshold = z_threshold
        self.min_ratio = min_ratio
        self.min_watch_ms = min_watch_ms
        self.warmup = warmup
        self.alpha = alpha
        self.guard_z = guard_z
        self.min_std = min_std
        self._baselines: dict[str, Baseline] = {}

    def observe(self, row: dict[str, object]) -> dict[str, object] | None:
        """Feed one closed (cdn, region) window; return an alert row or ``None``."""
        watch = int(row["watch_ms"]) + int(row["rebuffer_ms"])  # type: ignore[call-overload]
        if watch < self.min_watch_ms or row["cdn"] == "unknown":
            return None
        key = f"{row['cdn']}|{row['region']}"
        ratio = float(row["rebuffer_ratio"])  # type: ignore[arg-type]
        base = self._baselines.setdefault(key, Baseline())
        std = max(math.sqrt(base.var), self.min_std)
        z = (ratio - base.mean) / std if base.n else 0.0
        warmed_up = base.n >= self.warmup
        if not warmed_up or z < self.guard_z:
            base.update(ratio, self.alpha)
        if not (warmed_up and z >= self.z_threshold and ratio >= self.min_ratio):
            return None
        return {
            "window_start": row["window_start"],
            "window_end": row["window_end"],
            "cdn": row["cdn"],
            "region": row["region"],
            "rebuffer_ratio": ratio,
            "baseline_ratio": base.mean,
            "z_score": z,
            "watch_ms": watch,
            "severity": "critical" if z >= 2 * self.z_threshold else "warning",
        }

    def snapshot(self) -> dict[str, list[float]]:
        return {k: [b.mean, b.var, b.n] for k, b in sorted(self._baselines.items())}

    def restore(self, state: dict[str, list[float]]) -> None:
        self._baselines = {k: Baseline(v[0], v[1], int(v[2])) for k, v in state.items()}
