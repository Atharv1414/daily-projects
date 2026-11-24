import argparse
import json
import logging
import sys
from dataclasses import asdict
from pathlib import Path

import pymysql

from .config import load_config
from .db import AlreadyRunning, Database
from .http import Fetcher
from .pipeline import run_source


def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    names = args.source or list(config.sources)
    if unknown := set(names) - set(config.sources):
        raise ValueError(f"unknown source: {', '.join(sorted(unknown))}")
    fetcher = Fetcher(config.http)
    if args.dry_run:
        reports = [run_source(n, config, fetcher, None) for n in names]
    else:
        with Database() as db, db.exclusive():
            reports = [run_source(n, config, fetcher, db) for n in names]
    for report in reports:
        print(json.dumps(asdict(report)))
    return 2 if any(r.status == "failed" for r in reports) else 0


def migrate(_args: argparse.Namespace) -> int:
    with Database() as db, db.exclusive():
        print("applied:", ", ".join(db.migrate()) or "nothing to do")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harvest")
    parser.add_argument("--config", type=Path, default=Path("config/sources.yaml"))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(required=True)
    p = sub.add_parser("migrate", help="create or update the MySQL schema")
    p.set_defaults(func=migrate)
    p = sub.add_parser("run", help="scrape, clean and load")
    p.add_argument("source", nargs="*", help="default: every configured source")
    p.add_argument("--dry-run", action="store_true", help="do everything except the database")
    p.set_defaults(func=run)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stderr,
    )
    try:
        return args.func(args)
    except AlreadyRunning as exc:
        print(f"skipped: {exc}", file=sys.stderr)
        return 0  # the earlier run is still working, which is not an error for cron
    except (ValueError, OSError, pymysql.MySQLError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
