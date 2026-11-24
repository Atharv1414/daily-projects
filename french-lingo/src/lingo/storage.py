"""SQLite persistence. The only module that knows SQL."""

import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .srs import Card, Grade
from .user import User

MIGRATIONS = (
    """
    CREATE TABLE user (
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL UNIQUE COLLATE NOCASE,
      new_per_day INTEGER NOT NULL DEFAULT 10 CHECK (new_per_day BETWEEN 0 AND 100)
    );
    CREATE TABLE card (
      user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
      word_id TEXT NOT NULL,
      due TEXT NOT NULL,
      ease REAL NOT NULL CHECK (ease >= 1.3),
      interval INTEGER NOT NULL CHECK (interval >= 0),
      repetitions INTEGER NOT NULL,
      lapses INTEGER NOT NULL,
      PRIMARY KEY (user_id, word_id)
    ) WITHOUT ROWID;
    CREATE INDEX ix_card_due ON card (user_id, due);
    CREATE TABLE review (
      id INTEGER PRIMARY KEY,
      user_id INTEGER NOT NULL REFERENCES user(id) ON DELETE CASCADE,
      word_id TEXT NOT NULL,
      day TEXT NOT NULL,
      grade INTEGER NOT NULL CHECK (grade BETWEEN 0 AND 5),
      was_new INTEGER NOT NULL CHECK (was_new IN (0, 1)),
      seconds REAL NOT NULL CHECK (seconds >= 0)
    );
    CREATE INDEX ix_review_user_day ON review (user_id, day);
    """,
)


@dataclass(frozen=True)
class Review:
    word_id: str
    day: date
    grade: Grade
    was_new: bool
    seconds: float


class Storage:
    def __init__(self, path: Path | str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, isolation_level=None)
        self._db.execute("PRAGMA foreign_keys = ON")
        self._migrate()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version > len(MIGRATIONS):
            self._db.close()
            raise RuntimeError("This data was saved by a newer version of the app.")
        for number, script in enumerate(MIGRATIONS[version:], version + 1):
            self._db.executescript(f"BEGIN; {script} PRAGMA user_version = {number}; COMMIT;")

    def close(self) -> None:
        self._db.close()

    def users(self) -> list[User]:
        rows = self._db.execute("SELECT id, name, new_per_day FROM user ORDER BY name")
        return [User(*r) for r in rows]

    def add_user(self, name: str, new_per_day: int = 10) -> User:
        name = name.strip()
        User(0, name, new_per_day)  # validate first
        try:
            cursor = self._db.execute(
                "INSERT INTO user (name, new_per_day) VALUES (?, ?)", (name, new_per_day)
            )
        except sqlite3.IntegrityError:
            raise ValueError(f"There is already a learner called {name}.") from None
        return User(cursor.lastrowid, name, new_per_day)

    def cards(self, user: User) -> dict[str, Card]:
        rows = self._db.execute(
            "SELECT word_id, due, ease, interval, repetitions, lapses FROM card WHERE user_id = ?",
            (user.id,),
        )
        return {r[0]: Card(r[0], date.fromisoformat(r[1]), *r[2:]) for r in rows}

    def reviews(self, user: User) -> list[Review]:
        rows = self._db.execute(
            "SELECT word_id, day, grade, was_new, seconds FROM review WHERE user_id = ? "
            "ORDER BY id",
            (user.id,),
        )
        return [Review(w, date.fromisoformat(d), Grade(g), bool(n), s) for w, d, g, n, s in rows]

    def record(self, user: User, card: Card, review: Review) -> None:
        """The new schedule and its review are saved together, or not at all."""
        self._db.execute("BEGIN IMMEDIATE")
        try:
            self._db.execute(
                "INSERT INTO card VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (user_id, word_id) "
                "DO UPDATE SET due = excluded.due, ease = excluded.ease, "
                "interval = excluded.interval, repetitions = excluded.repetitions, "
                "lapses = excluded.lapses",
                (user.id, card.word_id, card.due.isoformat(), card.ease, card.interval,
                 card.repetitions, card.lapses),
            )  # fmt: skip
            self._db.execute(
                "INSERT INTO review (user_id, word_id, day, grade, was_new, seconds) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (user.id, review.word_id, review.day.isoformat(), int(review.grade),
                 review.was_new, review.seconds),
            )  # fmt: skip
        except BaseException:
            self._db.execute("ROLLBACK")
            raise
        self._db.execute("COMMIT")
