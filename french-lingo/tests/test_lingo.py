import json
import sqlite3
from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from lingo.__main__ import main
from lingo.answers import check, distance
from lingo.pack_loader import PackError, load_packs, parse_pack
from lingo.progress import ProgressTracker
from lingo.session import Session
from lingo.srs import MAX_INTERVAL, MIN_EASE, Card, Grade, review
from lingo.storage import Storage

DAY = date(2026, 1, 1)
PACKS, PROBLEMS = load_packs()
FRENCH = PACKS["french"]


@pytest.fixture
def storage():
    s = Storage(":memory:")
    yield s
    s.close()


@pytest.fixture
def user(storage):
    return storage.add_user("Léa", new_per_day=5)


def finish(session, right=True):
    """Answer every word; a wrong one is then corrected so the session ends."""
    missed = set()
    while word := session.current:
        ok = right or word.id in missed
        missed.add(word.id)
        session.answer(word.answers[0] if ok else "zzz", 3)


# --- scheduling


def test_sm2_intervals():
    card, today, seen = Card("w", DAY), DAY, []
    for _ in range(4):
        card = review(card, Grade.GOOD, today)
        seen.append(card.interval)
        today = card.due
    assert seen == [1, 6, 15, 38]


def test_forgetting_resets_and_counts_a_lapse():
    card = review(Card("w", DAY, interval=30, repetitions=5), Grade.WRONG, DAY)
    assert (card.interval, card.repetitions, card.lapses) == (1, 0, 1)
    assert review(Card("w", DAY), Grade.WRONG, DAY).lapses == 0


def test_hard_words_come_back_sooner():
    base = Card("w", DAY, interval=10, repetitions=3)
    gaps = [review(base, g, DAY).interval for g in (Grade.HARD, Grade.GOOD, Grade.EASY)]
    assert gaps == sorted(gaps) and len(set(gaps)) == 3


def test_overdue_success_earns_a_longer_gap():
    card = Card("w", DAY, interval=10, repetitions=3)
    late = review(card, Grade.GOOD, DAY + timedelta(days=20))
    assert late.interval > review(card, Grade.GOOD, DAY).interval


@given(st.lists(st.sampled_from(list(Grade)), max_size=60), st.integers(0, 40))
def test_schedule_invariants(grades, delay):
    card, today = Card("w", DAY), DAY
    for grade in grades:
        card = review(card, grade, today)
        assert card.ease >= MIN_EASE
        assert 1 <= card.interval <= MAX_INTERVAL
        assert card.due == today + timedelta(days=card.interval)
        today = card.due + timedelta(days=delay)


def test_leech_after_repeated_lapses():
    card = Card("w", DAY)
    for _ in range(4):
        card = review(review(card, Grade.GOOD, DAY), Grade.WRONG, DAY)
    assert card.is_leech


# --- answers


@pytest.mark.parametrize(
    "given_text,answer,seconds,grade",
    [
        ("la mère", "la mère", 2, Grade.EASY),
        (" La  Mère. ", "la mère", 8, Grade.GOOD),
        ("la mère", "la mère", 60, Grade.HARD),
        ("la mere", "la mère", 2, Grade.HARD),
        ("la soeur", "la sœur", 2, Grade.HARD),
        ("s’il vous plaît", "s'il vous plaît", 2, Grade.EASY),
        ("le formage", "le fromage", 2, Grade.HARD),
        ("le fromge", "le fromage", 2, Grade.HARD),
        ("la fromage", "le fromage", 2, Grade.WRONG),
        ("le pere", "la mère", 2, Grade.WRONG),
        ("nom", "non", 2, Grade.WRONG),
        ("", "non", 2, Grade.WRONG),
    ],
)
def test_marking(given_text, answer, seconds, grade):
    assert check(given_text, (answer,), seconds).grade is grade


def test_any_accepted_answer_counts():
    assert check("l'an", ("l'année", "l'an"), 1).correct


@given(st.text(max_size=8), st.text(max_size=8))
def test_distance_properties(a, b):
    assert distance(a, b) == distance(b, a)
    assert (distance(a, b) == 0) == (a == b)
    assert distance(a, b) <= max(len(a), len(b))


# --- packs


def test_bundled_packs_are_valid():
    assert PROBLEMS == []
    assert len(FRENCH.lessons) == 6 and len(FRENCH.words()) == 60
    for word in FRENCH.words().values():
        assert check(word.answers[0], word.answers, 1).grade is Grade.EASY


def pack(**changes):
    word = {"id": "eins", "prompt": "one", "answers": ["eins"]}
    lesson = {"id": "n", "title": "Numbers", "words": [word]}
    return {"id": "german", "name": "German", "lessons": [lesson], **changes}


def test_a_new_language_needs_only_a_file(tmp_path):
    (tmp_path / "german.json").write_text(json.dumps(pack()))
    packs, problems = load_packs(tmp_path)
    assert "german" in packs and not problems


def test_broken_packs_are_skipped_not_fatal(tmp_path):
    (tmp_path / "a.json").write_text("{nope")
    (tmp_path / "b.json").write_text(json.dumps(pack(id="french")))
    packs, problems = load_packs(tmp_path)
    assert set(packs) == {"french", "spanish"}
    assert len(problems) == 2


@pytest.mark.parametrize(
    "bad",
    [
        [],
        pack(id="Bad Id"),
        pack(name=""),
        pack(lessons=[]),
        pack(lessons=[{"id": "n", "title": "x", "words": []}]),
        pack(lessons=[{"id": "n", "title": "x", "words": [{"id": "a", "prompt": "p"}]}]),
        pack(lessons=pack()["lessons"] * 2),
    ],
)
def test_invalid_packs(bad):
    with pytest.raises(PackError):
        parse_pack(bad)


def test_packs_never_share_word_ids():
    assert not set(FRENCH.words()) & set(PACKS["spanish"].words())


# --- sessions


def test_new_words_are_limited_per_day_across_sessions(storage, user):
    first = Session(user, FRENCH, storage, DAY)
    assert first.remaining == 5
    for _ in range(3):
        first.answer(first.current.answers[0], 3)
    assert Session(user, FRENCH, storage, DAY).remaining == 2


def test_progress_survives_restart(tmp_path):
    path = tmp_path / "sub" / "p.db"
    storage = Storage(path)
    user = storage.add_user("Ana")
    finish(Session(user, FRENCH, storage, DAY))
    storage.close()
    again = Storage(path)
    assert len(again.cards(again.users()[0])) == 10
    again.close()


def test_missed_word_returns_but_is_scored_once(storage, user):
    session = Session(user, FRENCH, storage, DAY)
    word = session.current
    session.answer("zzz", 3)
    for _ in range(3):
        session.answer(session.current.answers[0], 3)
    assert session.current == word
    session.answer(word.answers[0], 3)
    assert [r.grade for r in storage.reviews(user) if r.word_id == word.id] == [Grade.WRONG]
    assert storage.cards(user)[word.id].repetitions == 0


def test_due_words_come_back_on_the_right_day(storage, user):
    finish(Session(user, FRENCH, storage, DAY))
    user = type(user)(user.id, user.name, 0)
    assert Session(user, FRENCH, storage, DAY).remaining == 0
    assert Session(user, FRENCH, storage, DAY + timedelta(days=1)).remaining == 5


def test_most_overdue_first(storage, user):
    ids = list(FRENCH.words())[:2]
    from lingo.storage import Review

    for word_id, due in zip(ids, (DAY, DAY - timedelta(days=9)), strict=True):
        storage.record(user, Card(word_id, due), Review(word_id, DAY, Grade.GOOD, False, 1))
    assert Session(user, FRENCH, storage, DAY).current.id == ids[1]


def test_lesson_session_stays_in_the_lesson(storage, user):
    lesson = FRENCH.lessons[2]
    session = Session(user, FRENCH, storage, DAY, lesson)
    assert session.current in lesson.words


def test_learners_are_separate(storage, user):
    finish(Session(user, FRENCH, storage, DAY))
    other = storage.add_user("Tom")
    assert storage.cards(other) == {}


def test_finished_session_refuses_answers(storage, user):
    session = Session(user, FRENCH, storage, DAY)
    finish(session)
    with pytest.raises(RuntimeError):
        session.answer("x", 1)


# --- storage


@pytest.mark.parametrize("name", ["", "  ", "x" * 41, "LÉA".replace("É", "é")])
def test_bad_or_duplicate_names(storage, user, name):
    with pytest.raises(ValueError):
        storage.add_user(name)


def test_record_is_atomic(storage, user):
    from lingo.storage import Review

    with pytest.raises(sqlite3.IntegrityError):
        storage.record(user, Card("w", DAY), Review("w", DAY, Grade.GOOD, True, -1))
    assert storage.cards(user) == {} and storage.reviews(user) == []


def test_newer_database_is_refused(tmp_path):
    path = tmp_path / "p.db"
    Storage(path).close()
    db = sqlite3.connect(path)
    db.execute("PRAGMA user_version = 99")
    db.close()
    with pytest.raises(RuntimeError, match="newer"):
        Storage(path)


# --- progress


def tracker(storage, user, day):
    return ProgressTracker(user, FRENCH, storage, day)


def test_empty_progress(storage, user):
    t = tracker(storage, user, DAY)
    assert t.retention() is None and t.streak() == 0 and t.weak_words() == []
    assert t.counts() == {"new": 60, "learning": 0, "mature": 0, "due": 0}


def test_retention_ignores_first_sightings(storage, user):
    finish(Session(user, FRENCH, storage, DAY), right=False)
    assert tracker(storage, user, DAY).retention() is None
    user = type(user)(user.id, user.name, 0)
    session = Session(user, FRENCH, storage, DAY + timedelta(days=1))
    session.answer("zzz", 1)
    finish(session)
    assert tracker(storage, user, DAY + timedelta(days=1)).retention() == 0.8


def test_weak_areas(storage, user):
    from lingo.storage import Review

    good, bad = FRENCH.lessons[0].words[0], FRENCH.lessons[1].words[0]
    for n in range(4):
        for word, grade in ((good, Grade.GOOD), (bad, Grade.WRONG)):
            result = Review(word.id, DAY + timedelta(days=n), grade, False, 1)
            storage.record(user, Card(word.id, DAY), result)
    t = tracker(storage, user, DAY + timedelta(days=4))
    assert [a.label for a in t.weak_lessons()] == ["Family"]
    assert t.weak_words()[0].label == "la mère" and t.weak_words()[0].accuracy == 0


def test_streak(storage, user):
    for n in (0, 2, 3, 4):
        finish(Session(user, FRENCH, storage, DAY + timedelta(days=n)))
    assert tracker(storage, user, DAY + timedelta(days=4)).streak() == 3
    assert tracker(storage, user, DAY + timedelta(days=5)).streak() == 3
    assert tracker(storage, user, DAY + timedelta(days=6)).streak() == 0


def test_forecast_and_daily(storage, user):
    finish(Session(user, FRENCH, storage, DAY))
    t = tracker(storage, user, DAY)
    assert t.forecast() == [0, 5, 0, 0, 0, 0, 0]
    assert tracker(storage, user, DAY + timedelta(days=9)).forecast()[0] == 5
    assert t.daily()[-1] == (DAY, 5, 5) and len(t.daily()) == 14


def test_list_packs(tmp_path, capsys):
    assert main(["--data", str(tmp_path), "--list-packs"]) == 0
    assert "French: 6 lessons, 60 words" in capsys.readouterr().out
