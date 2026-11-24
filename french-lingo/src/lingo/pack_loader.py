"""Find language packs. A new language is one JSON file: no code changes."""

import json
import re
from importlib.resources import files
from pathlib import Path

from .lesson import LanguagePack, Lesson, Word

IDENT = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")


class PackError(ValueError):
    pass


def _ident(value: object, where: str) -> str:
    if not isinstance(value, str) or not IDENT.fullmatch(value):
        raise PackError(f"{where}: ids use lower-case letters, numbers and hyphens")
    return value


def _text(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PackError(f"{where} is missing")
    return value.strip()


def _items(value: object, where: str) -> list[dict]:
    if not isinstance(value, list) or not value or not all(isinstance(v, dict) for v in value):
        raise PackError(f"{where} must be a list with at least one entry")
    return value


def parse_pack(data: object) -> LanguagePack:
    if not isinstance(data, dict):
        raise PackError("a pack must be a JSON object")
    pack_id = _ident(data.get("id"), "pack")
    lessons, seen = [], set()
    for raw in _items(data.get("lessons"), "lessons"):
        lesson_id = _ident(raw.get("id"), "lesson")
        words = []
        for w in _items(raw.get("words"), f"{lesson_id} words"):
            # Ids are namespaced by pack, so two packs can never share progress by accident.
            word_id = f"{pack_id}:{_ident(w.get('id'), f'{lesson_id} word')}"
            if word_id in seen:
                raise PackError(f"duplicate word id {word_id}")
            seen.add(word_id)
            answers = w.get("answers")
            if not isinstance(answers, list) or not answers:
                raise PackError(f"{word_id}: answers must be a list")
            words.append(
                Word(
                    word_id,
                    _text(w.get("prompt"), f"{word_id} prompt"),
                    tuple(_text(a, f"{word_id} answer") for a in answers),
                    str(w.get("example", "")),
                )
            )
        lessons.append(Lesson(lesson_id, _text(raw.get("title"), "title"), tuple(words)))
    if len({x.id for x in lessons}) != len(lessons):
        raise PackError("duplicate lesson id")
    return LanguagePack(pack_id, _text(data.get("name"), "name"), tuple(lessons))


def load_packs(extra: Path | None = None) -> tuple[dict[str, LanguagePack], list[str]]:
    """Returns packs and problems: one broken pack must not stop the others loading."""
    sources = [p for p in files("lingo").joinpath("packs").iterdir() if p.name.endswith(".json")]
    if extra and extra.is_dir():
        sources += sorted(extra.glob("*.json"))
    packs, problems = {}, []
    for source in sorted(sources, key=lambda p: p.name):
        try:
            pack = parse_pack(json.loads(source.read_text(encoding="utf-8")))
            if pack.id in packs:
                raise PackError(f"pack id {pack.id!r} is already used")
            packs[pack.id] = pack
        except (PackError, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            problems.append(f"{source.name}: {exc}")
    return packs, problems
