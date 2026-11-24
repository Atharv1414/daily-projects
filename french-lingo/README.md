# 🇫🇷 French Lingo

A desktop vocabulary trainer that schedules each word for each learner with spaced repetition.

**Role focus:** Software Engineer · **Stack:** Python (standard library only), Tkinter, SQLite, pytest + Hypothesis

Design decisions are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Features

- **Spaced repetition:** SM-2, with credit for remembering overdue words and detection of words that keep being forgotten.
- **Fair marking:** accents and small typos earn a "hard" pass, but the wrong article (*la fromage*) is wrong. Slow answers count as harder.
- **Several learners**, each with their own schedule and daily limit, saved in SQLite after every answer.
- **Dashboard:** 30-day retention, streak, weakest lessons and words, reviews per day and a 7-day forecast.
- **Language packs:** 60 French words in 6 lessons, plus a Spanish sample. A new language is one JSON file.

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```
```bash
.venv/bin/french-lingo
```

It needs a Python with Tkinter (on Homebrew: `brew install python-tk`).

## Add a language

Put a file in `~/.french-lingo/packs/`, then check it with `french-lingo --list-packs`:

```json
{"id": "german", "name": "German", "lessons": [
  {"id": "numbers", "title": "Numbers", "words": [
    {"id": "eins", "prompt": "one", "answers": ["eins"]}]}]}
```

A broken pack is reported and skipped. The others still load.

## Tests

53 tests, including property-based tests of the scheduler and tests that drive the real window. The two window tests are skipped where there is no display.

```bash
.venv/bin/pytest
```

## License

MIT
