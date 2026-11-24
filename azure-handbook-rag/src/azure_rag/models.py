from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str
    title: str
    content: str


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


@dataclass(frozen=True)
class Answer:
    text: str
    sources: list[Hit] = field(default_factory=list)  # only the chunks actually cited
    numbers: list[int] = field(default_factory=list)  # citation number of each source


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class Generator(Protocol):
    def generate(self, instructions: str, prompt: str) -> str: ...


class Store(Protocol):
    def ensure_index(self) -> None: ...
    def existing_ids(self) -> set[str]: ...
    def upload(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...
    def delete(self, ids: set[str]) -> None: ...
    def search(self, query: str, vector: list[float], top: int) -> list[Hit]: ...
