"""Command line: run the API, or export the JSON contract the web app is tested against."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import DEMO_TOKEN, Settings

# The exact requests the web app's tests replay. Keep in sync with web/src/api.js.
CONTRACT_REQUESTS: tuple[str, ...] = (
    "/api/health",
    "/api/races?season=2026",
    "/api/races/scar-edge-horseshoe",
    "/api/races/raven-crag-race",
    "/api/races/scar-edge-horseshoe/results?season=2026&page=1&page_size=50",
    "/api/races/scar-edge-horseshoe/results?season=2026&sex=F&page=1&page_size=50",
    "/api/standings?season=2026&sex=F",
    "/api/standings?season=2026&sex=M",
    "/api/records",
    "/api/runners?q=ruth",
    "/api/runners/R0090",
    "/api/ghost?race=scar-edge-horseshoe&season=2026&runners=R0090,R0084",
)


UPLOAD_URL = "/api/races/raven-crag-race/results"


def sample_upload(client) -> dict:
    """A realistic organiser upload: one new finisher, one DNF and one unknown runner id."""
    taken = {
        r["runner_id"]
        for r in client.get(UPLOAD_URL, params={"season": 2026, "page_size": 200}).json()["items"]
    }
    free = [f"R{i:04d}" for i in range(1, 421) if f"R{i:04d}" not in taken]
    return {
        "upload_id": "raven-2026-late-entries",
        "season": 2026,
        "results": [
            {"runner_id": free[0], "status": "finished", "splits": [812, 1466], "version": 1},
            {"runner_id": free[1], "status": "dnf", "splits": [1035], "version": 1},
            {"runner_id": "R9999", "status": "finished", "splits": [790, 1388], "version": 1},
        ],
    }


def export_contract(out: Path) -> dict:
    from fastapi.testclient import TestClient

    from .app import create_app

    client = TestClient(create_app(Settings(log_level="WARNING")))
    examples = {}
    for url in CONTRACT_REQUESTS:
        response = client.get(url)
        response.raise_for_status()
        examples[url] = response.json()
    upload = sample_upload(client)
    reply = client.post(UPLOAD_URL, json=upload, headers={"Authorization": f"Bearer {DEMO_TOKEN}"})
    reply.raise_for_status()
    contract = {
        "about": "Responses from the seeded API (seed 2026). The API tests check that the API "
        "still returns exactly these; the web tests use them as their mock server.",
        "examples": examples,
        "upload": {"url": UPLOAD_URL, "request": upload, "response": reply.json()},
    }
    out.write_text(json.dumps(contract, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return contract


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fell-results")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run the API with uvicorn")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    contract = sub.add_parser("export-contract", help="write contract/examples.json")
    contract.add_argument("--out", type=Path, default=Path("../contract/examples.json"))
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from .app import create_app

        uvicorn.run(create_app(), host=args.host, port=args.port)
    else:
        data = export_contract(args.out)
        print(f"wrote {len(data['examples'])} examples to {args.out}")


if __name__ == "__main__":
    main()
