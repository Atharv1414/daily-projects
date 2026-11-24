"""Command line: build, validate, report, export and serve."""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from . import datagen, export, warehouse
from .config import BiError, Settings
from .metrics import FY25, FY26, Metrics
from .security import USERS, issue_token
from .validation import run_checks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="law-bi", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="generate sources and build the mart")
    build.add_argument("--seed", type=int, default=2026)
    sub.add_parser("validate", help="run reconciliation checks")
    kpis = sub.add_parser("kpis", help="KPIs, variance and realisation for a user")
    kpis.add_argument("--user", choices=sorted(USERS), default="mp")
    kpis.add_argument("--unit")
    restate = sub.add_parser("restate", help="explain changes to a month since it was reported")
    restate.add_argument("--user", choices=sorted(USERS), default="mp")
    restate.add_argument("--unit")
    restate.add_argument("--month", type=date.fromisoformat, default=date(2026, 4, 1))
    restate.add_argument("--reported", type=date.fromisoformat, default=date(2026, 4, 30))
    restate.add_argument("--restated", type=date.fromisoformat, default=date(2026, 10, 31))
    sub.add_parser("export", help="write dashboards, charts and the validation report")
    serve = sub.add_parser("serve", help="run the dashboard and API")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--demo", action="store_true", help="random key, prints login links")
    return parser


def _run(args: argparse.Namespace, settings: Settings) -> int:
    if args.command == "build":
        sources = datagen.generate(datagen.GenConfig(seed=args.seed))
        with warehouse.open_database(settings.database) as con:
            timings = warehouse.build(con, sources)
            print(json.dumps({k: len(v) for k, v in sources.items()}))
            audit = con.execute("SELECT * FROM load_audit").fetchone()
            print("raw {}, duplicates {}, quarantined {}".format(*audit))
            print(f"models built in {sum(timings.values()):.2f}s")
        return 0
    with warehouse.open_database(settings.database, read_only=True) as con:
        if args.command == "validate":
            checks = run_checks(con)
            for c in checks:
                print(f"{'PASS' if c.ok else 'FAIL'}  {c.name}  ({c.detail})")
            return 0 if all(c.ok for c in checks) else 1
        if args.command == "kpis":
            metrics = Metrics(con, USERS[args.user])
            print(f"{'metric':<26}{'FY25':>16}{'FY26':>16}")
            before, now = metrics.kpis(FY25, args.unit), metrics.kpis(FY26, args.unit)
            for key in now:
                cells = [f"{v:,.1f}" if v is not None else "-" for v in (before[key], now[key])]
                print(f"{key:<26}{cells[0]:>16}{cells[1]:>16}")
            print("\nnet value variance")
            for key, value in metrics.variance(FY25, FY26, args.unit).items():
                print(f"  {key:<10}{value:>16,.0f}")
        elif args.command == "restate":
            metrics = Metrics(con, USERS[args.user])
            for s in metrics.restatement(args.month, args.reported, args.restated, args.unit):
                count = "" if s["entries"] is None else f"{s['entries']:>6} entries"
                print(f"{s['step']:<18}{s['amount']:>14,.2f}{count:>16}")
        elif args.command == "export":
            ok = export.write_validation(con, Path("docs/VALIDATION.md"))
            paths = export.export_dashboards(con, Path("dashboard"))
            paths += export.export_charts(con, Path("docs/charts"))
            print("\n".join(map(str, paths)))
            return 0 if ok else 1
        elif args.command == "serve":
            import uvicorn

            from .api import create_app

            if args.demo:
                settings = replace(settings, signing_key=secrets.token_hex(32))
                for user_id in USERS:
                    token = issue_token(user_id, settings.signing_key, settings.token_ttl_seconds)
                    url = f"http://{args.host}:{args.port}/login?token={token}"
                    print(f"{user_id:<18} {url}", flush=True)
            # uvicorn's access log would print login tokens; the app logs paths itself.
            uvicorn.run(create_app(con, settings), host=args.host, port=args.port, access_log=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s %(message)s")
    try:
        return _run(args, Settings())
    except (BiError, FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
