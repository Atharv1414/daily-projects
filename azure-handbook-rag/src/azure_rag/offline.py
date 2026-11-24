"""Stand-ins that run without Azure. They exercise the pipeline, not real model quality."""

import hashlib
import math
import re

from .models import Chunk, Hit

STOP = set("a an and are as at be by can do does for from have how i if in is it many me much my "
           "of on or should the to we what when where which who with you your".split())  # fmt: skip
MIN_OVERLAP = 2


def _words(text: str) -> list[str]:
    return [w.rstrip("s") for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP]


class HashEmbedder:
    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._one(t) for t in texts]

    @staticmethod
    def _one(text: str, size: int = 512) -> list[float]:
        vector = [0.0] * size
        for word in _words(text):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % size] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


class MemoryStore:
    def __init__(self) -> None:
        self.rows: dict[str, tuple[Chunk, list[float]]] = {}

    def ensure_index(self) -> None:
        pass

    def existing_ids(self) -> set[str]:
        return set(self.rows)

    def upload(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        for chunk, vector in zip(chunks, vectors, strict=True):
            self.rows[chunk.id] = (chunk, vector)

    def delete(self, ids: set[str]) -> None:
        for i in ids:
            self.rows.pop(i, None)

    def search(self, query: str, vector: list[float], top: int) -> list[Hit]:
        wanted = set(_words(query))
        hits = []
        for chunk, stored in self.rows.values():
            if len(wanted & set(_words(f"{chunk.title} {chunk.content}"))) >= MIN_OVERLAP:
                hits.append(Hit(chunk, sum(a * b for a, b in zip(vector, stored, strict=True))))
        return sorted(hits, key=lambda h: h.score, reverse=True)[:top]


class ExtractiveGenerator:
    """Returns the first passage, cited. There is no language model here."""

    def generate(self, instructions: str, prompt: str) -> str:
        match = re.search(r'<passage number="1"[^>]*>\n(.*?)\n</passage>', prompt, re.S)
        return f"{match[1]} [1]" if match else "NOT_FOUND"
