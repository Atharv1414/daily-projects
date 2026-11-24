"""Analytics over the review history: retention, weak areas, streak and forecast."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from .lesson import LanguagePack
from .srs import Grade
from .storage import Storage
from .user import User

MATURE_DAYS = 21
MIN_REVIEWS = 3


@dataclass(frozen=True)
class WeakArea:
    label: str
    reviews: int
    accuracy: float


class ProgressTracker:
    def __init__(self, user: User, pack: LanguagePack, storage: Storage, today: date) -> None:
        self._pack, self._today = pack, today
        words = pack.words()
        self._words = words
        self._cards = {k: c for k, c in storage.cards(user).items() if k in words}
        self._reviews = [r for r in storage.reviews(user) if r.word_id in words]

    def retention(self, days: int = 30) -> float | None:
        """Share of reviews remembered. First sightings are excluded: nothing to retain yet."""
        since = self._today - timedelta(days=days - 1)
        recent = [r for r in self._reviews if r.day >= since and not r.was_new]
        return sum(r.grade >= Grade.HARD for r in recent) / len(recent) if recent else None

    def daily(self, days: int = 14) -> list[tuple[date, int, int]]:
        """(day, reviews, correct), including days with none."""
        total, right = Counter(), Counter()
        for r in self._reviews:
            total[r.day] += 1
            right[r.day] += r.grade >= Grade.HARD
        span = [self._today - timedelta(days=n) for n in reversed(range(days))]
        return [(d, total[d], right[d]) for d in span]

    def counts(self) -> dict[str, int]:
        mature = sum(c.interval >= MATURE_DAYS for c in self._cards.values())
        return {
            "new": len(self._words) - len(self._cards),
            "learning": len(self._cards) - mature,
            "mature": mature,
            "due": sum(c.due <= self._today for c in self._cards.values()),
        }

    def _weak(self, group) -> list[WeakArea]:
        results = defaultdict(list)
        for r in self._reviews:
            results[group(r.word_id)].append(r.grade >= Grade.HARD)
        areas = [
            WeakArea(label, len(rs), sum(rs) / len(rs))
            for label, rs in results.items()
            if len(rs) >= MIN_REVIEWS and not all(rs)
        ]
        # Laplace smoothing stops a word seen three times outranking one missed forty times.
        areas.sort(key=lambda a: ((a.accuracy * a.reviews + 1) / (a.reviews + 2), a.label))
        return areas

    def weak_lessons(self) -> list[WeakArea]:
        lesson_of = self._pack.lesson_of()
        return self._weak(lambda i: lesson_of[i].title)

    def weak_words(self, limit: int = 5) -> list[WeakArea]:
        return self._weak(lambda i: self._words[i].answers[0])[:limit]

    def leeches(self) -> list[str]:
        return sorted(self._words[i].answers[0] for i, c in self._cards.items() if c.is_leech)

    def streak(self) -> int:
        """Days in a row up to today; a streak is not lost until today is over."""
        days = {r.day for r in self._reviews}
        day = self._today if self._today in days else self._today - timedelta(days=1)
        n = 0
        while day in days:
            n, day = n + 1, day - timedelta(days=1)
        return n

    def forecast(self, days: int = 7) -> list[int]:
        """Reviews falling due each day; overdue ones count as today's."""
        out = [0] * days
        for card in self._cards.values():
            offset = max(0, (card.due - self._today).days)
            if offset < days:
                out[offset] += 1
        return out
