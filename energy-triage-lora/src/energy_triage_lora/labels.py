"""The triage schema: what every message must be labelled with, and how labels become text."""

from __future__ import annotations

from dataclasses import dataclass

CATEGORIES: tuple[str, ...] = (
    "billing",
    "meter_reading",
    "smart_meter",
    "payment_support",
    "switching",
    "supply_fault",
    "tariff",
    "moving_home",
)
URGENCIES: tuple[str, ...] = ("low", "medium", "high")
VULNERABLE: tuple[str, ...] = ("no", "yes")

FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("category", CATEGORIES),
    ("urgency", URGENCIES),
    ("vulnerable", VULNERABLE),
)


class LabelError(ValueError):
    """Raised when a label or a model's output does not fit the schema."""


@dataclass(frozen=True, slots=True)
class Triage:
    category: str
    urgency: str
    vulnerable: str

    def __post_init__(self) -> None:
        for name, allowed in FIELDS:
            value = getattr(self, name)
            if value not in allowed:
                raise LabelError(f"{name}={value!r} is not one of {allowed}")

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.category, self.urgency, self.vulnerable)

    def to_tokens(self) -> list[str]:
        """The answer as three special tokens, which is what the model learns to emit."""
        return [label_token(name, getattr(self, name)) for name, _ in FIELDS]

    def to_text(self) -> str:
        return "; ".join(f"{name}={getattr(self, name)}" for name, _ in FIELDS)

    @classmethod
    def from_text(cls, text: str) -> Triage:
        parts = dict(part.strip().split("=", 1) for part in text.split(";") if "=" in part)
        try:
            return cls(parts["category"], parts["urgency"], parts["vulnerable"])
        except KeyError as missing:
            raise LabelError(f"missing field {missing}") from None


def label_token(field: str, value: str) -> str:
    return f"<{field}:{value}>"


def all_label_tokens() -> list[str]:
    return [label_token(name, value) for name, values in FIELDS for value in values]


def parse_tokens(tokens: list[str]) -> Triage:
    """Reads the first three generated tokens back into a Triage, or raises LabelError."""
    if len(tokens) < len(FIELDS):
        raise LabelError(f"expected {len(FIELDS)} label tokens, got {len(tokens)}")
    values = []
    for (name, allowed), token in zip(FIELDS, tokens, strict=False):
        prefix = f"<{name}:"
        if not (token.startswith(prefix) and token.endswith(">")):
            raise LabelError(f"expected a {name} token, got {token!r}")
        value = token[len(prefix) : -1]
        if value not in allowed:
            raise LabelError(f"{value!r} is not a valid {name}")
        values.append(value)
    return Triage(*values)
