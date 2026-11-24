"""Cleaning (fix what is safely fixable), then schema validation (reject the rest)."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, ValidationError

from .extract import Raw

RATINGS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
PRICE = re.compile(r"£\s*(\d{1,3}(?:,\d{3})*|\d+)\.(\d{2})")
Text = Annotated[str, Field(min_length=1)]


class Book(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    external_id: Annotated[str, Field(min_length=1, max_length=255)]
    title: Annotated[str, Field(min_length=1, max_length=300)]
    url: Annotated[str, Field(max_length=500)]
    category: Annotated[str, Field(min_length=1, max_length=100)]
    price_pence: Annotated[int, Field(gt=0, lt=10_000_000)]
    rating: Annotated[int, Field(ge=1, le=5)]
    in_stock: bool


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    digest: Annotated[str, Field(min_length=64, max_length=64)]
    text: Annotated[str, Field(min_length=1, max_length=5000)]
    author: Annotated[str, Field(min_length=1, max_length=150)]
    tags: tuple[Annotated[str, Field(min_length=1, max_length=60)], ...]


Record = Book | Quote


@dataclass(frozen=True)
class Rejected:
    raw: Raw
    reason: str


@dataclass
class Cleaned:
    records: list[Record] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    duplicates: int = 0

    @property
    def reject_rate(self) -> float:
        total = len(self.records) + len(self.rejected)
        return len(self.rejected) / total if total else 0.0


def tidy(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = unicodedata.normalize("NFC", value).replace(" ", " ").replace("​", "")
    return re.sub(r"\s+", " ", value).strip() or None


def pence(value: object) -> int | None:
    """Whole pence from an exact '£1,234.56'. Anything ambiguous is rejected, not guessed."""
    match = PRICE.fullmatch(tidy(value) or "")
    return int(Decimal(match[1].replace(",", "")) * 100) + int(match[2]) if match else None


def stock(value: object) -> bool | None:
    text = (tidy(value) or "").lower()
    if text.startswith("in stock"):
        return True
    return False if text.startswith("out of stock") else None


def external_id(url: object) -> str | None:
    """The stable part of the address: /catalogue/<slug>_<id>/index.html"""
    match = re.search(r"/([^/]+)/index\.html$", url) if isinstance(url, str) else None
    return match[1] if match else None


def clean_book(raw: Raw) -> Book:
    url = raw.get("url")
    if isinstance(url, str):
        HttpUrl(url)
    return Book.model_validate(
        {
            "external_id": external_id(url),
            "title": tidy(raw.get("title")),
            "url": url,
            "category": tidy(raw.get("category")),
            "price_pence": pence(raw.get("price")),
            "rating": RATINGS.get((tidy(raw.get("rating")) or "").lower()),
            "in_stock": stock(raw.get("availability")),
        }
    )


def clean_quote(raw: Raw) -> Quote:
    text = (tidy(raw.get("text")) or "").strip('“”" ') or None
    author = tidy(raw.get("author"))
    tags = raw.get("tags")
    cleaned = {(tidy(t) or "").lower() for t in tags} - {""} if isinstance(tags, list) else set()
    digest = hashlib.sha256(f"{author}\0{text}".casefold().encode()).hexdigest()
    return Quote.model_validate(
        {"digest": digest, "text": text, "author": author, "tags": tuple(sorted(cleaned))}
    )


CLEANERS = {"books": clean_book, "quotes": clean_quote}


def key(record: Record) -> str:
    return record.external_id if isinstance(record, Book) else record.digest


def clean(source: str, raws: list[Raw]) -> Cleaned:
    result, seen = Cleaned(), set()
    for raw in raws:
        try:
            record = CLEANERS[source](raw)
        except ValidationError as exc:
            reasons = [f"{'.'.join(map(str, e['loc'])) or 'url'}: {e['msg']}" for e in exc.errors()]
            result.rejected.append(Rejected(raw, "; ".join(reasons)[:500]))
            continue
        if key(record) in seen:
            result.duplicates += 1
        else:
            seen.add(key(record))
            result.records.append(record)
    return result
