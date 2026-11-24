"""Split Markdown/text into heading-aware chunks with a small overlap."""

import hashlib
import re
from pathlib import Path

from .models import Chunk

HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*#*$")


def _sections(text: str, default_title: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    title, lines = default_title, []
    for line in text.splitlines():
        if match := HEADING.match(line):
            if body := "\n".join(lines).strip():
                sections.append((title, body))
            title, lines = match[1], []
        else:
            lines.append(line)
    if body := "\n".join(lines).strip():
        sections.append((title, body))
    return sections


def _windows(words: list[str], size: int, overlap: int) -> list[str]:
    if len(words) <= size:
        return [" ".join(words)]
    step = size - overlap
    return [" ".join(words[i : i + size]) for i in range(0, len(words) - overlap, step)]


def chunk_text(source: str, text: str, size: int = 220, overlap: int = 40) -> list[Chunk]:
    """IDs hash the content, so unchanged text keeps its ID and is not embedded again."""
    if not 0 <= overlap < size:
        raise ValueError("overlap must be at least 0 and smaller than size")
    chunks: dict[str, Chunk] = {}
    for title, body in _sections(text, Path(source).stem):
        for content in _windows(body.split(), size, overlap):
            key = hashlib.sha256(f"{source}\0{title}\0{content}".encode()).hexdigest()[:32]
            chunks[key] = Chunk(key, source, title, content)
    return list(chunks.values())


def load_folder(folder: Path) -> list[Chunk]:
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    chunks: list[Chunk] = []
    for path in sorted(folder.rglob("*")):
        if path.is_file() and path.suffix.lower() in {".md", ".txt"}:
            source = path.relative_to(folder).as_posix()
            chunks += chunk_text(source, path.read_text(encoding="utf-8"))
    return chunks
