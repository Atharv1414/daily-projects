"""A byte-level BPE tokenizer, trained from scratch on the pre-training text.

Byte-level means no character is ever unknown: anything outside the learned merges falls back to
its UTF-8 bytes. Digits are split one by one before merging, so account numbers and meter readings
do not bloat the vocabulary with tokens that will never repeat.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from pathlib import Path

from .labels import all_label_tokens

SPECIALS = ["<pad>", "<bos>", "<sep>", "<eos>", *all_label_tokens()]
PRE_TOKEN = re.compile(r" ?[A-Za-z]+| ?\d| ?[^\sA-Za-z\d]+|\s+")


class Tokenizer:
    def __init__(self, merges: list[tuple[int, int]]) -> None:
        self.merges = merges
        self.ranks = {pair: i for i, pair in enumerate(merges)}
        # Ids: specials first, then the 256 bytes, then one id per merge.
        self.special_ids = {tok: i for i, tok in enumerate(SPECIALS)}
        self.byte_offset = len(SPECIALS)
        self.vocab: dict[int, bytes] = {self.byte_offset + b: bytes([b]) for b in range(256)}
        for i, (a, b) in enumerate(merges):
            self.vocab[self.byte_offset + 256 + i] = self.vocab[a] + self.vocab[b]
        self._cache: dict[str, list[int]] = {}

    @property
    def size(self) -> int:
        return self.byte_offset + 256 + len(self.merges)

    def id(self, special: str) -> int:
        return self.special_ids[special]

    def token(self, token_id: int) -> str:
        if token_id < self.byte_offset:
            return SPECIALS[token_id]
        return self.vocab[token_id].decode("utf-8", errors="replace")

    @classmethod
    def train(cls, texts: Iterable[str], num_merges: int = 700, min_count: int = 2) -> Tokenizer:
        words = Counter(w for text in texts for w in PRE_TOKEN.findall(text))
        offset = len(SPECIALS)
        pieces = {w: [offset + b for b in w.encode("utf-8")] for w in words}
        merges: list[tuple[int, int]] = []
        for step in range(num_merges):
            pairs: Counter[tuple[int, int]] = Counter()
            for word, count in words.items():
                ids = pieces[word]
                for pair in zip(ids, ids[1:], strict=False):
                    pairs[pair] += count
            if not pairs:
                break
            best, count = max(pairs.items(), key=lambda kv: (kv[1], -kv[0][0], -kv[0][1]))
            if count < min_count:
                break
            new_id = offset + 256 + step
            merges.append(best)
            for word in words:
                pieces[word] = _merge(pieces[word], best, new_id)
        return cls(merges)

    def _encode_word(self, word: str) -> list[int]:
        if word in self._cache:
            return self._cache[word]
        ids = [self.byte_offset + b for b in word.encode("utf-8")]
        while len(ids) > 1:
            ranked = [
                (self.ranks.get(pair, 1 << 30), i)
                for i, pair in enumerate(zip(ids, ids[1:], strict=False))
            ]
            rank, _ = min(ranked)
            if rank == 1 << 30:
                break
            ids = _merge(ids, self.merges[rank], self.byte_offset + 256 + rank)
        if len(self._cache) < 50_000:
            self._cache[word] = ids
        return ids

    def encode(self, text: str) -> list[int]:
        return [i for word in PRE_TOKEN.findall(text) for i in self._encode_word(word)]

    def decode(self, ids: Iterable[int]) -> str:
        out = bytearray()
        for i in ids:
            if i < self.byte_offset:
                out.extend(SPECIALS[i].encode())
            else:
                out.extend(self.vocab[i])
        return out.decode("utf-8", errors="replace")

    def save(self, path: Path) -> None:
        path.write_text(json.dumps({"merges": self.merges}), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> Tokenizer:
        return cls([tuple(m) for m in json.loads(path.read_text(encoding="utf-8"))["merges"]])


def _merge(ids: list[int], pair: tuple[int, int], new_id: int) -> list[int]:
    out: list[int] = []
    i = 0
    while i < len(ids):
        if i + 1 < len(ids) and ids[i] == pair[0] and ids[i + 1] == pair[1]:
            out.append(new_id)
            i += 2
        else:
            out.append(ids[i])
            i += 1
    return out
