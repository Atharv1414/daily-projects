"""Merchant normalisation and automatic categorisation.

Precedence (first match wins):
1. user rules (priority below ``DEFAULT_PRIORITY``),
2. the category this merchant was most often filed under before ("learned" history),
3. built-in keyword rules for common UK merchants,
4. ``other``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .models import CategoryRule

DEFAULT_PRIORITY = 200

DEFAULT_RULES: tuple[CategoryRule, ...] = tuple(
    CategoryRule(pattern, category, DEFAULT_PRIORITY)
    for pattern, category in (
        (
            r"(?i)\b(tesco|sainsbury'?s?|asda|aldi|lidl|waitrose|co-?op|morrisons|"
            r"pret|greggs|deliveroo|just eat|nando'?s|costa|starbucks|uber eats)\b",
            "food",
        ),
        (r"(?i)\b(tfl|trainline|uber|bolt|national rail|shell|bp|esso|stagecoach)\b", "transport"),
        (r"(?i)\b(rent|letting|council tax|mortgage|foxtons)\b", "housing"),
        (
            r"(?i)\b(octopus|british gas|edf|thames water|bt|virgin media|vodafone|ee|"
            r"three|sky)\b",
            "utilities",
        ),
        (
            r"(?i)\b(netflix|spotify|disney|odeon|cineworld|vue|ticketmaster|steam)\b",
            "entertainment",
        ),
        (r"(?i)\b(boots|superdrug|pharmacy|puregym|the gym|nhs|bupa|specsavers)\b", "health"),
        (r"(?i)\b(amazon|amzn|asos|argos|currys|john lewis|ikea|primark|zara|h&m)\b", "shopping"),
    )
)

_PREFIX = re.compile(
    r"(?i)^(card payment to|contactless payment to|contactless|direct debit to|"
    r"standing order to|faster payment to)\s+"
)
_CARD_REF = re.compile(r"\*\S*")
_ON_DATE = re.compile(r"(?i)\bon \d{1,2}[ /-]\w{2,3}([ /-]\d{2,4})?\b")
_LONG_NUMBER = re.compile(r"\b\d{3,}\b")
_JUNK = re.compile(r"[^\w&' .-]")
_SPACES = re.compile(r"\s+")


def normalise_merchant(raw: str) -> str:
    """Turn ``'CARD PAYMENT TO TESCO STORES 2231*1234 ON 03 NOV'`` into ``'Tesco Stores'``."""
    text = _PREFIX.sub("", raw.strip())
    text = _CARD_REF.sub("", text)
    text = _ON_DATE.sub("", text)
    text = _LONG_NUMBER.sub("", text)
    text = _JUNK.sub(" ", text)
    text = _SPACES.sub(" ", text).strip(" .-")
    return text.title()


@dataclass(frozen=True)
class Categorisation:
    category: str
    reason: str


class Categorizer:
    def __init__(
        self,
        rules: Iterable[CategoryRule] = (),
        history: Mapping[str, str] | None = None,
        fallback: str = "other",
    ) -> None:
        ordered = sorted([*rules, *DEFAULT_RULES], key=lambda r: r.priority)
        self._user = [(re.compile(r.pattern), r) for r in ordered if r.priority < DEFAULT_PRIORITY]
        self._builtin = [
            (re.compile(r.pattern), r) for r in ordered if r.priority >= DEFAULT_PRIORITY
        ]
        self._history = dict(history or {})
        self._fallback = fallback

    def categorize(self, merchant: str) -> Categorisation:
        for regex, rule in self._user:
            if regex.search(merchant):
                return Categorisation(rule.category, f"rule:{rule.pattern}")
        if merchant in self._history:
            return Categorisation(self._history[merchant], "history")
        for regex, rule in self._builtin:
            if regex.search(merchant):
                return Categorisation(rule.category, "builtin")
        return Categorisation(self._fallback, "fallback")
