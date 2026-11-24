"""SM-2 spaced repetition, as a pure function: (card, grade, today) -> card."""

from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import IntEnum

MIN_EASE = 1.3
START_EASE = 2.5
MAX_INTERVAL = 365
LEECH_LAPSES = 4


class Grade(IntEnum):
    """SM-2 quality scores. Anything below 3 means the word was forgotten."""

    WRONG = 1
    HARD = 3
    GOOD = 4
    EASY = 5


@dataclass(frozen=True)
class Card:
    word_id: str
    due: date
    ease: float = START_EASE
    interval: int = 0
    repetitions: int = 0
    lapses: int = 0

    @property
    def is_leech(self) -> bool:
        """Forgotten so often that it needs a different approach, not just more repeats."""
        return self.lapses >= LEECH_LAPSES


def review(card: Card, grade: Grade, today: date) -> Card:
    miss = 5 - grade
    ease = max(MIN_EASE, card.ease + 0.1 - miss * (0.08 + miss * 0.02))
    if grade < Grade.HARD:
        # Only a word that had been learned counts as a lapse.
        lapses = card.lapses + (card.repetitions > 0)
        return replace(card, ease=ease, interval=1, repetitions=0, lapses=lapses,
                       due=today + timedelta(days=1))  # fmt: skip
    if card.repetitions == 0:
        interval = 1
    elif card.repetitions == 1:
        interval = 6
    else:
        # Remembering an overdue word earns credit for the extra days it was remembered.
        late = max(0, (today - card.due).days)
        interval = max(card.interval + 1, round((card.interval + late / 2) * ease))
    interval = min(interval, MAX_INTERVAL)
    return replace(card, ease=ease, interval=interval, repetitions=card.repetitions + 1,
                   due=today + timedelta(days=interval))  # fmt: skip
