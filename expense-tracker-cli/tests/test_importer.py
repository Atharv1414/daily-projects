import csv
import io

import pytest

from expense_tracker.categorizer import Categorizer
from expense_tracker.datagen import write_sample_statements
from expense_tracker.errors import ImportFormatError
from expense_tracker.importer import StatementImporter, resolve_columns
from expense_tracker.repository import ExpenseRepository, ImportRunRepository

STATEMENT = """Date,Description,Amount
2026-11-01,CARD PAYMENT TO TESCO STORES 2231*1234,-23.40
01/11/2026,TFL TRAVEL CH,-6.80
02/11/2026,TFL TRAVEL CH,-6.80
02/11/2026,TFL TRAVEL CH,-6.80
2026-11-03,ACME LTD SALARY,"3,125.00"
2026-11-04,,-9.99
31/02/2026,NETFLIX.COM,-10.99
2026-11-05,BOOTS 1182,N/A
2026-11-06,AMZN MKTP UK*XY12,"-£1,049.00"
"""


def _rows(text):
    reader = csv.DictReader(io.StringIO(text))
    return list(reader), reader.fieldnames


@pytest.fixture
def importer(conn):
    return StatementImporter(ExpenseRepository(conn), ImportRunRepository(conn), Categorizer())


def test_import_parses_categorises_and_reports(importer):
    rows, fields = _rows(STATEMENT)
    result = importer.import_rows(rows, fields, "test.csv")
    assert (result.rows_read, result.inserted, result.credits_skipped) == (9, 5, 1)
    assert sorted(r.reason for r in result.rejected) == [
        "Invalid amount: 'N/A'",
        "Unrecognised date '31/02/2026'",
        "missing description",
    ]
    stored = {(e.merchant, e.category, e.amount_pence) for e in importer.expenses.iter()}
    assert ("Tesco Stores", "food", 2340) in stored
    assert ("Amzn Mktp Uk", "shopping", 104900) in stored


def test_same_day_identical_purchases_are_kept_but_reimport_is_noop(importer):
    rows, fields = _rows(STATEMENT)
    importer.import_rows(rows, fields, "a.csv")
    tfl = [e for e in importer.expenses.iter() if e.merchant == "Tfl Travel Ch"]
    assert len(tfl) == 3  # two identical fares on 2 Nov are both real
    again = importer.import_rows(rows, fields, "a.csv")
    assert (again.inserted, again.duplicates) == (0, 5)
    runs = importer.runs.list()
    assert [r.status for r in runs] == ["succeeded", "succeeded"]
    assert runs[0].counts["duplicates"] == 5


def test_debit_credit_layout_and_header_aliases(importer):
    text = (
        "Transaction Date,Details,Paid out,Paid in\n"
        "03/11/2026,SPOTIFY UK,11.99,\n"
        "03/11/2026,REFUND,,5.00\n"
    )
    rows, fields = _rows(text)
    result = importer.import_rows(rows, fields, "b.csv")
    assert (result.inserted, result.credits_skipped) == (1, 1)


def test_missing_columns_raise_clear_error():
    with pytest.raises(ImportFormatError, match="amount"):
        resolve_columns(["Date", "Description"])
    with pytest.raises(ImportFormatError, match="header"):
        resolve_columns(None)


def test_failed_import_is_atomic_and_audited(importer, monkeypatch):
    rows, fields = _rows(STATEMENT)

    def explode(_batch):
        raise RuntimeError("disk full")

    monkeypatch.setattr(importer.expenses, "add_many", explode)
    with pytest.raises(RuntimeError):
        importer.import_rows(rows, fields, "c.csv")
    assert importer.expenses.count() == 0
    assert importer.runs.list()[0].status == "failed"


def test_overlapping_sample_statements_deduplicate(importer, tmp_path):
    a, b = write_sample_statements(tmp_path, seed=1)
    first = importer.import_file(a, quarantine_path=tmp_path / "rejected.csv")
    second = importer.import_file(b)
    assert first.inserted > 500 and second.duplicates > 50
    assert (tmp_path / "rejected.csv").read_text().startswith("line,reason")
    total = importer.expenses.count()
    assert importer.import_file(a).inserted == 0 and importer.import_file(b).inserted == 0
    assert importer.expenses.count() == total
