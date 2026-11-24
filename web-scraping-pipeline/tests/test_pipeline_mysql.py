import os
from datetime import date

import pymysql
import pytest
from conftest import ROOT

from harvest.cli import main
from harvest.config import load_config, mysql_options
from harvest.db import AlreadyRunning, Database, statements
from harvest.extract import BooksSource
from harvest.pipeline import run_source


def count(db, table):
    return db.query(f"SELECT COUNT(*) FROM {table}")[0][0]


def run(name, config, fetcher, db):
    return run_source(name, config, fetcher, db)


def test_dry_run_needs_no_database(config, fetcher):
    report = run_source("books", config, fetcher, None)
    assert (report.status, report.loaded, report.duplicates) == ("succeeded", 4, 1)


def test_failed_source_is_reported_not_raised(site, config, fetcher):
    site.pages["/"] = "redesigned"
    report = run_source("books", config, fetcher, None)
    assert report.status == "failed" and "LayoutChanged" in report.message


def test_config_and_urls(monkeypatch):
    assert set(load_config(ROOT / "config/sources.yaml").sources) == {"books", "quotes"}
    assert mysql_options("mysql://u:p%40ss@h/d")["password"] == "p@ss"
    for bad in ("", "http://h/d", "mysql://h"):
        monkeypatch.setenv("HARVEST_MYSQL_URL", bad)
        with pytest.raises(ValueError):
            mysql_options()


def test_cli_without_database_is_a_clean_error(monkeypatch, capsys):
    monkeypatch.delenv("HARVEST_MYSQL_URL", raising=False)
    assert main(["migrate"]) == 1
    assert "HARVEST_MYSQL_URL" in capsys.readouterr().err


def test_end_to_end_load(config, fetcher, db):
    assert run("books", config, fetcher, db).status == "succeeded"
    assert run("quotes", config, fetcher, db).status == "succeeded"
    assert (count(db, "book"), count(db, "quote"), count(db, "quote_tag")) == (4, 2, 3)
    row = db.query("SELECT category, price_gbp, in_stock FROM current_book WHERE title=%s",
                   ("Café Guide",))[0]  # fmt: skip
    assert row == ("Travel", 1020, 0)
    assert db.query("SELECT status, loaded, duplicates FROM pipeline_run WHERE source='books'") == (
        [("succeeded", 4, 1)]
    )


def test_rerun_is_idempotent(config, fetcher, db):
    for _ in range(3):
        run("books", config, fetcher, db)
        run("quotes", config, fetcher, db)
    assert (count(db, "book"), count(db, "book_price"), count(db, "quote_tag")) == (4, 4, 3)
    assert count(db, "pipeline_run") == 6


def test_price_history_and_changes(config, fetcher, db):
    from harvest.clean import clean

    source = BooksSource(fetcher, str(config.sources["books"].url), 50)
    records = clean("books", list(source.records())).records
    run_id = db.start_run("books")
    db.load(run_id, records, date(2026, 1, 1))
    cheaper = [r.model_copy(update={"price_pence": 100}) for r in records]
    db.load(run_id, cheaper, date(2026, 1, 2))
    assert count(db, "book_price") == 8
    assert {p for (p,) in db.query("SELECT price_gbp FROM current_book")} == {1}


def test_load_is_all_or_nothing(config, fetcher, db, monkeypatch):
    original = Database._many

    def fail_on_prices(self, sql, rows):
        if "book_price" in sql:
            raise pymysql.OperationalError(2013, "lost connection")
        original(self, sql, rows)

    monkeypatch.setattr(Database, "_many", fail_on_prices)
    report = run("books", config, fetcher, db)
    assert report.status == "failed" and report.loaded == 0
    assert (count(db, "book"), count(db, "category")) == (0, 0)
    assert db.query("SELECT status FROM pipeline_run") == [("failed",)]


def test_rejects_are_quarantined(site, config, fetcher, db):
    path = "/catalogue/category/travel/page-2.html"
    site.pages[path] = site.pages[path].replace("£9.99", "free")
    assert run("books", config, fetcher, db).rejected == 1
    reason, title = db.query("SELECT reason, raw->>'$.title' FROM rejected_record")[0]
    assert "price_pence" in reason and title == "C Book"


def test_too_many_rejects_blocks_the_load(site, config, fetcher, db):
    for path, html in site.pages.items():
        site.pages[path] = html.replace("£", "$")
    report = run("books", config, fetcher, db)
    assert report.status == "failed"
    assert count(db, "book") == 0 and count(db, "rejected_record") > 0


def test_missing_page_makes_a_partial_run(site, config, fetcher, db):
    site.faults["/catalogue/category/travel/page-2.html"] = [(404, {})]
    report = run("books", config, fetcher, db)
    assert (report.status, report.loaded, report.failed_pages) == ("partial", 3, 1)


def test_overlapping_runs_are_refused(db):
    with Database() as other, db.exclusive(), pytest.raises(AlreadyRunning), other.exclusive():
        pass
    with Database() as other, other.exclusive():
        pass  # released


def test_crashed_run_is_closed_by_the_next(db):
    db.start_run("books")
    db.start_run("books")
    assert [s for (s,) in db.query("SELECT status FROM pipeline_run ORDER BY id")] == [
        "failed",
        "running",
    ]


def test_migrations_run_once(db):
    assert db.migrate(ROOT / "schema") == []


def test_names_that_mysql_treats_as_equal(db):
    from harvest.clean import Quote

    quotes = [
        Quote(digest=c * 64, text=c, author=a, tags=(t,))
        for c, a, t in (("a", "José", "café"), ("b", "JOSE", "cafe"))
    ]
    db.load(db.start_run("quotes"), quotes, date(2026, 1, 1))
    assert count(db, "quote") == 2 and count(db, "quote_tag") == 2


def test_database_enforces_the_rules_too(db):
    with pytest.raises(pymysql.MySQLError):
        db.query("INSERT INTO book_price VALUES (999, '2026-01-01', 5, 1)")


def test_analytics_queries_run(config, fetcher, db):
    run("books", config, fetcher, db)
    for sql in statements((ROOT / "schema/analytics.sql").read_text()):
        db.query(sql)


def test_lookup_queries_use_indexes(config, fetcher, db):
    run("books", config, fetcher, db)
    plan = db.query("EXPLAIN FORMAT=JSON SELECT id FROM book WHERE external_id = 'a-book_1'")
    assert "uq_book_external" in plan[0][0]
    plan = db.query(
        "EXPLAIN FORMAT=JSON SELECT price_pence FROM book_price FORCE INDEX (ix_price_day) "
        "WHERE observed_on = '2026-01-01'"
    )
    assert '"using_index": true' in plan[0][0]


def test_cli_end_to_end(site, db, tmp_path, capsys):
    path = tmp_path / "c.yaml"
    path.write_text(
        f"http: {{requests_per_second: 1000}}\nsources:\n  books: {{url: '{site.url}/'}}\n"
    )
    assert os.environ["HARVEST_MYSQL_URL"]
    assert main(["--config", str(path), "run"]) == 0
    assert '"loaded": 4' in capsys.readouterr().out
    assert main(["--config", str(path), "run", "nope"]) == 1
