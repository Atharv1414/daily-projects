"""Bank statement CSV import: header detection, validation, quarantine and deduplication.

Design notes
------------
* **Idempotent.** Every imported row gets a content hash of (date, normalised merchant,
  amount, occurrence-number-within-file). Re-importing the same file, or an overlapping
  statement from a later month, inserts nothing twice, while two genuinely identical
  purchases on the same day in one file are both kept.
* **Atomic.** Accepted rows are written in a single transaction: an import either fully
  lands or leaves the database untouched.
* **Nothing silently dropped.** Unparseable rows are collected with a reason and can be
  written to a quarantine CSV; every run is recorded in ``import_runs`` for auditing.
"""

from __future__ import annotations

import csv
import hashlib
import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

from .categorizer import Categorizer, normalise_merchant
from .errors import ImportFormatError, ValidationError
from .models import Expense, parse_date
from .money import parse_money
from .repository import ExpenseRepository, ImportRunRepository

log = logging.getLogger(__name__)

HEADER_ALIASES: dict[str, set[str]] = {
    "date": {"date", "transaction date", "posted date", "value date", "posting date"},
    "description": {"description", "merchant", "details", "payee", "narrative", "reference"},
    "amount": {"amount", "value", "amount (gbp)", "amount gbp"},
    "debit": {"debit", "paid out", "money out", "withdrawals"},
    "credit": {"credit", "paid in", "money in", "deposits"},
}


@dataclass(frozen=True)
class RejectedRow:
    line: int
    reason: str
    raw: dict[str, str]


@dataclass
class ImportResult:
    source: str
    rows_read: int = 0
    inserted: int = 0
    duplicates: int = 0
    credits_skipped: int = 0
    rejected: list[RejectedRow] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        data = asdict(self)
        data.pop("source")
        data["rejected"] = len(self.rejected)
        return data


def resolve_columns(fieldnames: Sequence[str] | None) -> dict[str, str]:
    """Map canonical column names to the file's actual headers (case/space-insensitive)."""
    if not fieldnames:
        raise ImportFormatError("File has no header row")
    lookup = {name.strip().lower(): name for name in fieldnames if name}
    resolved = {}
    for canonical, aliases in HEADER_ALIASES.items():
        match = next((lookup[a] for a in aliases if a in lookup), None)
        if match:
            resolved[canonical] = match
    missing = [c for c in ("date", "description") if c not in resolved]
    if "amount" not in resolved and "debit" not in resolved:
        missing.append("amount (or debit/credit)")
    if missing:
        raise ImportFormatError(f"Missing required column(s): {', '.join(missing)}")
    return resolved


def parse_row(row: Mapping[str, str | None], cols: Mapping[str, str]) -> tuple[date, str, int]:
    """Return (date, raw description, signed pence). Negative = money out."""

    def cell(name: str) -> str:
        return (row.get(cols[name]) or "").strip() if name in cols else ""

    raw_date = cell("date")
    if not raw_date:
        raise ValidationError("missing date")
    spent_on = parse_date(raw_date)
    description = cell("description")
    if not description:
        raise ValidationError("missing description")
    if "amount" in cols:
        amount_text = cell("amount")
        if not amount_text:
            raise ValidationError("missing amount")
        signed = parse_money(amount_text, allow_negative=True)
    else:
        debit, credit = cell("debit"), cell("credit")
        if debit and credit:
            raise ValidationError("both debit and credit populated")
        if debit:
            signed = -abs(parse_money(debit, allow_negative=True))
        elif credit:
            signed = abs(parse_money(credit, allow_negative=True))
        else:
            raise ValidationError("missing amount")
    return spent_on, description, signed


def row_hash(spent_on: date, merchant: str, pence: int, occurrence: int) -> str:
    key = f"{spent_on.isoformat()}|{merchant.lower()}|{pence}|{occurrence}"
    return hashlib.sha256(key.encode()).hexdigest()[:32]


class StatementImporter:
    def __init__(
        self,
        expenses: ExpenseRepository,
        runs: ImportRunRepository,
        categorizer: Categorizer,
    ) -> None:
        self.expenses = expenses
        self.runs = runs
        self.categorizer = categorizer

    def import_file(self, path: Path, quarantine_path: Path | None = None) -> ImportResult:
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            result = self.import_rows(reader, reader.fieldnames, source=str(path))
        if quarantine_path and result.rejected:
            write_quarantine(result.rejected, quarantine_path)
        return result

    def import_rows(
        self,
        rows: Iterable[Mapping[str, str | None]],
        fieldnames: Sequence[str] | None,
        source: str,
    ) -> ImportResult:
        cols = resolve_columns(fieldnames)
        result = ImportResult(source)
        run_id = self.runs.start(source)
        try:
            batch = self._prepare(rows, cols, result)
            inserted = self.expenses.add_many(batch)
            result.inserted = inserted
            result.duplicates = len(batch) - inserted
        except Exception:
            self.runs.finish(run_id, "failed", result.counts())
            log.exception("import failed", extra={"source": source})
            raise
        self.runs.finish(run_id, "succeeded", result.counts())
        log.info("import finished", extra={"source": source, **result.counts()})
        return result

    def _prepare(
        self,
        rows: Iterable[Mapping[str, str | None]],
        cols: Mapping[str, str],
        result: ImportResult,
    ) -> list[Expense]:
        seen: Counter[tuple[date, str, int]] = Counter()
        batch: list[Expense] = []
        for line_no, row in enumerate(rows, start=2):  # line 1 is the header
            result.rows_read += 1
            try:
                spent_on, description, signed = parse_row(row, cols)
            except ValidationError as exc:
                raw = {k: v or "" for k, v in row.items() if k is not None}
                result.rejected.append(RejectedRow(line_no, str(exc), raw))
                continue
            if signed > 0:
                result.credits_skipped += 1  # salary, refunds, transfers in
                continue
            merchant = normalise_merchant(description) or "Unknown"
            amount = -signed
            key = (spent_on, merchant, amount)
            seen[key] += 1
            batch.append(
                Expense(
                    amount_pence=amount,
                    category=self.categorizer.categorize(merchant).category,
                    spent_on=spent_on,
                    merchant=merchant,
                    source="import",
                    import_hash=row_hash(*key, seen[key]),
                )
            )
        return batch


def write_quarantine(rejected: Sequence[RejectedRow], path: Path) -> None:
    columns = sorted({k for r in rejected for k in r.raw})
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["line", "reason", *columns])
        for r in rejected:
            writer.writerow([r.line, r.reason, *(r.raw.get(c, "") for c in columns)])
