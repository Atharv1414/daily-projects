"""Command-line entry point: ``gym-booking serve | seed | demo | report``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from .clock import utc_now


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gym-booking", description="Gym Class Booking API")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the API with uvicorn")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    seed_cmd = sub.add_parser("seed", help="fill the configured database with a synthetic timetable")
    seed_cmd.add_argument("--members", type=int, default=120)

    sub.add_parser("demo", help="print an end-to-end booking walkthrough (in-memory database)")
    report = sub.add_parser("report", help="seed an in-memory database and print the utilisation report")
    report.add_argument("--members", type=int, default=120)

    args = parser.parse_args(argv)
    if args.command == "serve":  # pragma: no cover - starts a server
        import uvicorn

        from .main import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
    elif args.command == "seed":
        from .config import Settings
        from .main import create_app
        from .seed import STAFF_EMAIL, STAFF_PASSWORD, seed

        settings = Settings.from_env()
        app = create_app(settings)
        with app.state.session_factory() as db:
            summary = seed(db, settings, utc_now(), members=args.members)
        app.state.engine.dispose()
        print(f"Seeded {summary.classes} classes and {summary.members} members into {settings.database_url}")
        print(f"Staff login: {STAFF_EMAIL} / {STAFF_PASSWORD}")
    elif args.command == "demo":
        from .demo import run_demo

        run_demo()
    else:
        from .demo import run_report

        run_report(args.members)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
