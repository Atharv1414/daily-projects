"""Decide how good a typed answer is, forgiving accents and small slips."""

import re
import unicodedata
from dataclasses import dataclass

from .srs import Grade

SLOW_SECONDS = 12.0
FAST_SECONDS = 4.0


@dataclass(frozen=True)
class Verdict:
    grade: Grade
    note: str = ""

    @property
    def correct(self) -> bool:
        return self.grade >= Grade.HARD


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold().replace("’", "'")
    return re.sub(r"\s+", " ", text).strip(" .!?")


def strip_accents(text: str) -> str:
    text = text.replace("œ", "oe").replace("æ", "ae")
    return "".join(c for c in unicodedata.normalize("NFD", text) if not unicodedata.combining(c))


def distance(a: str, b: str) -> int:
    """Edit distance, counting a swap of neighbouring letters as one edit."""
    rows = [list(range(len(b) + 1))]
    for i, x in enumerate(a, 1):
        row = [i]
        for j, y in enumerate(b, 1):
            best = min(rows[-1][j] + 1, row[j - 1] + 1, rows[-1][j - 1] + (x != y))
            if i > 1 and j > 1 and x == b[j - 2] and a[i - 2] == y:
                best = min(best, rows[-2][j - 2] + 1)
            row.append(best)
        rows.append(row)
    return rows[-1][-1]


def check(given: str, accepted: tuple[str, ...], seconds: float) -> Verdict:
    guess = normalise(given)
    targets = [normalise(a) for a in accepted]
    if not guess:
        return Verdict(Grade.WRONG)
    if guess in targets:
        if seconds <= FAST_SECONDS:
            return Verdict(Grade.EASY)
        return Verdict(Grade.GOOD if seconds <= SLOW_SECONDS else Grade.HARD)
    plain = strip_accents(guess)
    for target in targets:
        if plain == strip_accents(target):
            return Verdict(Grade.HARD, "Check the accents.")
    for target in targets:
        # A typo in a short word is often a different word, so allow it only in longer ones,
        # and never in the article: "le" for "la" is a gender mistake, not a slip.
        same_start = target.split(" ")[0] == guess.split(" ")[0] or " " not in target
        if len(target) >= 6 and same_start and distance(plain, strip_accents(target)) == 1:
            return Verdict(Grade.HARD, "Nearly: check the spelling.")
    return Verdict(Grade.WRONG)
