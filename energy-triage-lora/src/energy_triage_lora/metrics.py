"""Scores for triage predictions. Exact match and vulnerable-customer recall matter most:
a mislabelled category costs a transfer, a missed vulnerable customer can cost far more."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .labels import CATEGORIES, FIELDS, Triage


@dataclass(frozen=True, slots=True)
class Scores:
    n: int
    exact_match: float
    category_accuracy: float
    category_macro_f1: float
    urgency_accuracy: float
    vulnerable_accuracy: float
    vulnerable_recall: float
    vulnerable_precision: float
    high_urgency_recall: float

    def as_dict(self) -> dict[str, float]:
        return {k: round(float(getattr(self, k)), 4) for k in self.__slots__}


def macro_f1(truth: Sequence[str], predicted: Sequence[str], classes: Sequence[str]) -> float:
    scores = []
    for c in classes:
        tp = sum(t == c and p == c for t, p in zip(truth, predicted, strict=True))
        fp = sum(t != c and p == c for t, p in zip(truth, predicted, strict=True))
        fn = sum(t == c and p != c for t, p in zip(truth, predicted, strict=True))
        if tp + fp + fn == 0:
            continue
        scores.append(2 * tp / (2 * tp + fp + fn))
    return float(np.mean(scores)) if scores else 0.0


def _recall(truth: Sequence[str], predicted: Sequence[str], positive: str) -> float:
    hits = [p == positive for t, p in zip(truth, predicted, strict=True) if t == positive]
    return float(np.mean(hits)) if hits else 1.0


def _precision(truth: Sequence[str], predicted: Sequence[str], positive: str) -> float:
    hits = [t == positive for t, p in zip(truth, predicted, strict=True) if p == positive]
    return float(np.mean(hits)) if hits else 1.0


def score(truth: Sequence[Triage], predicted: Sequence[Triage]) -> Scores:
    if len(truth) != len(predicted) or not truth:
        raise ValueError("need the same, non-zero number of labels and predictions")
    col = {
        name: ([getattr(t, name) for t in truth], [getattr(p, name) for p in predicted])
        for name, _ in FIELDS
    }
    acc = {name: float(np.mean([a == b for a, b in zip(*col[name], strict=True)])) for name in col}
    return Scores(
        n=len(truth),
        exact_match=float(np.mean([t == p for t, p in zip(truth, predicted, strict=True)])),
        category_accuracy=acc["category"],
        category_macro_f1=macro_f1(*col["category"], CATEGORIES),
        urgency_accuracy=acc["urgency"],
        vulnerable_accuracy=acc["vulnerable"],
        vulnerable_recall=_recall(*col["vulnerable"], "yes"),
        vulnerable_precision=_precision(*col["vulnerable"], "yes"),
        high_urgency_recall=_recall(*col["urgency"], "high"),
    )


def expected_calibration_error(
    confidence: Sequence[float], correct: Sequence[bool], bins: int = 10
) -> float:
    """Average gap between how sure the model was and how often it was right.

    Weighted by the number of predictions in each confidence bin.
    """
    conf = np.asarray(confidence, dtype=float)
    hit = np.asarray(correct, dtype=float)
    edges = np.linspace(0, 1, bins + 1)
    total = 0.0
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        mask = (conf > lo) & (conf <= hi) if lo > 0 else (conf >= lo) & (conf <= hi)
        if mask.any():
            total += mask.mean() * abs(conf[mask].mean() - hit[mask].mean())
    return float(total)


def coverage_curve(
    confidence: Sequence[float], correct: Sequence[bool]
) -> list[tuple[float, float, float]]:
    """(threshold, share answered, exact-match accuracy on those), most confident first."""
    conf = np.asarray(confidence, dtype=float)
    hit = np.asarray(correct, dtype=bool)
    order = np.argsort(-conf, kind="stable")
    cumulative = np.cumsum(hit[order])
    out = []
    for k in range(1, len(order) + 1):
        out.append((float(conf[order[k - 1]]), k / len(order), float(cumulative[k - 1] / k)))
    return out


def threshold_for(confidence: Sequence[float], correct: Sequence[bool], target: float) -> float:
    """The lowest confidence threshold whose answered messages still reach the target accuracy.
    Chosen on validation data and then applied unchanged to the test sets."""
    best = 1.0
    for threshold, _coverage, accuracy in coverage_curve(confidence, correct):
        if accuracy >= target:
            best = threshold
    return best
