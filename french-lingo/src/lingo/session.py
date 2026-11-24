"""One sitting: choose words, mark answers, repeat the missed ones, save as you go."""

from collections import deque
from datetime import date

from .answers import Verdict, check
from .lesson import LanguagePack, Lesson, Word
from .srs import Card, review
from .storage import Review, Storage
from .user import User

REPEAT_AFTER = 3


class Session:
    def __init__(
        self,
        user: User,
        pack: LanguagePack,
        storage: Storage,
        today: date,
        lesson: Lesson | None = None,
    ) -> None:
        self.user, self._storage, self._today = user, storage, today
        self._words = pack.words()
        self._cards = storage.cards(user)
        self._queue = deque(self._choose(pack, lesson))
        self._saved: set[str] = set()
        self.answered = self.correct = 0

    def _choose(self, pack: LanguagePack, lesson: Lesson | None) -> list[str]:
        scope = [w.id for w in (lesson.words if lesson else self._words.values())]
        due = [i for i in scope if i in self._cards and self._cards[i].due <= self._today]
        # Most overdue first, then hardest first.
        due.sort(key=lambda i: (self._cards[i].due, self._cards[i].ease, i))
        new_today = sum(
            r.was_new and r.day == self._today and r.word_id in self._words
            for r in self._storage.reviews(self.user)
        )
        allowance = max(0, self.user.new_per_day - new_today)
        return due + [i for i in scope if i not in self._cards][:allowance]

    @property
    def remaining(self) -> int:
        return len(self._queue)

    @property
    def current(self) -> Word | None:
        return self._words[self._queue[0]] if self._queue else None

    def answer(self, text: str, seconds: float) -> Verdict:
        word = self.current
        if word is None:
            raise RuntimeError("The session is finished.")
        verdict = check(text, word.answers, seconds)
        if word.id not in self._saved:  # a repeat is practice and must not alter the schedule
            before = self._cards.get(word.id)
            card = review(before or Card(word.id, self._today), verdict.grade, self._today)
            result = Review(word.id, self._today, verdict.grade, before is None, max(0.0, seconds))
            self._storage.record(self.user, card, result)
            self._cards[word.id] = card
            self._saved.add(word.id)
            self.answered += 1
            self.correct += verdict.correct
        self._queue.popleft()
        if not verdict.correct:
            self._queue.insert(min(REPEAT_AFTER, len(self._queue)), word.id)
        return verdict
