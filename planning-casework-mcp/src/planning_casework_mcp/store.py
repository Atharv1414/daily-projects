"""SQLite persistence for the casework system, with schema versioning and an audit log."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path

from .domain import (
    Application,
    Constraint,
    ConsulteeResponse,
    DecisionDraft,
    Policy,
    PublicComment,
    Recommendation,
    Stance,
    Status,
)

SCHEMA_VERSION = 2

MIGRATIONS: dict[int, str] = {
    1: """
    CREATE TABLE applications (
        ref TEXT PRIMARY KEY, app_type TEXT NOT NULL, is_major INTEGER NOT NULL,
        is_eia INTEGER NOT NULL, description TEXT NOT NULL, address TEXT NOT NULL,
        ward TEXT NOT NULL, applicant TEXT NOT NULL,
        applicant_is_member_or_staff INTEGER NOT NULL, councillor_call_in INTEGER NOT NULL,
        received TEXT NOT NULL, validated TEXT, consultation_start TEXT,
        extension_agreed_to TEXT, status TEXT NOT NULL, case_officer TEXT NOT NULL
    );
    CREATE INDEX ix_app_ward_status ON applications(ward, status);
    CREATE TABLE constraints (ref TEXT NOT NULL REFERENCES applications(ref),
        kind TEXT NOT NULL, detail TEXT NOT NULL);
    CREATE INDEX ix_constraints_ref ON constraints(ref);
    CREATE TABLE consultees (ref TEXT NOT NULL REFERENCES applications(ref),
        consultee TEXT NOT NULL, response TEXT NOT NULL, summary TEXT NOT NULL);
    CREATE INDEX ix_consultees_ref ON consultees(ref);
    CREATE TABLE comments (comment_id INTEGER PRIMARY KEY,
        ref TEXT NOT NULL REFERENCES applications(ref), address TEXT NOT NULL,
        stance TEXT NOT NULL, text TEXT NOT NULL, received TEXT NOT NULL);
    CREATE INDEX ix_comments_ref ON comments(ref);
    CREATE TABLE policies (policy_id TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL);
    CREATE TABLE audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL, tool TEXT NOT NULL,
        args TEXT NOT NULL, outcome TEXT NOT NULL);
    """,
    2: """
    CREATE TABLE drafts (draft_id INTEGER PRIMARY KEY,
        ref TEXT NOT NULL REFERENCES applications(ref), recommendation TEXT NOT NULL,
        reasons TEXT NOT NULL, conditions TEXT NOT NULL, route TEXT NOT NULL,
        approved_by TEXT NOT NULL, created_at TEXT NOT NULL,
        idempotency_key TEXT NOT NULL UNIQUE);
    CREATE TABLE extensions (id INTEGER PRIMARY KEY,
        ref TEXT NOT NULL REFERENCES applications(ref), previous_date TEXT,
        new_date TEXT NOT NULL, reason TEXT NOT NULL, approved_by TEXT NOT NULL,
        created_at TEXT NOT NULL);
    """,
}


class NotFound(LookupError):
    pass


def _d(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


class CaseStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self.migrate()

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    # ---- schema ------------------------------------------------------------------------

    def schema_version(self) -> int:
        return int(self._conn.execute("PRAGMA user_version").fetchone()[0])

    def migrate(self) -> None:
        current = self.schema_version()
        for version in range(current + 1, SCHEMA_VERSION + 1):
            with self._conn:
                self._conn.executescript(MIGRATIONS[version])
                self._conn.execute(f"PRAGMA user_version = {version}")

    # ---- loading -----------------------------------------------------------------------

    def insert_applications(self, apps: Iterable[Application]) -> None:
        rows = [
            (
                a.ref, a.app_type.value, int(a.is_major), int(a.is_eia), a.description,
                a.address, a.ward, a.applicant, int(a.applicant_is_member_or_staff),
                int(a.councillor_call_in), a.received.isoformat(),
                a.validated.isoformat() if a.validated else None,
                a.consultation_start.isoformat() if a.consultation_start else None,
                a.extension_agreed_to.isoformat() if a.extension_agreed_to else None,
                a.status.value, a.case_officer,
            )
            for a in apps
        ]  # fmt: skip
        with self.tx() as c:
            c.executemany(f"INSERT INTO applications VALUES ({','.join('?' * 16)})", rows)

    def insert_constraints(self, rows: Iterable[tuple[str, Constraint]]) -> None:
        with self.tx() as c:
            c.executemany(
                "INSERT INTO constraints VALUES (?,?,?)",
                [(ref, k.kind, k.detail) for ref, k in rows],
            )

    def insert_consultees(self, rows: Iterable[tuple[str, ConsulteeResponse]]) -> None:
        with self.tx() as c:
            c.executemany(
                "INSERT INTO consultees VALUES (?,?,?,?)",
                [(ref, r.consultee, r.response, r.summary) for ref, r in rows],
            )

    def insert_comments(self, rows: Iterable[tuple[str, PublicComment]]) -> None:
        with self.tx() as c:
            c.executemany(
                "INSERT INTO comments VALUES (?,?,?,?,?,?)",
                [
                    (p.comment_id, ref, p.address, p.stance.value, p.text, p.received.isoformat())
                    for ref, p in rows
                ],
            )

    def insert_policies(self, policies: Iterable[Policy]) -> None:
        with self.tx() as c:
            c.executemany(
                "INSERT INTO policies VALUES (?,?,?)",
                [(p.policy_id, p.title, p.text) for p in policies],
            )

    # ---- queries -----------------------------------------------------------------------

    @staticmethod
    def _app(row: sqlite3.Row) -> Application:
        return Application(
            ref=row["ref"],
            app_type=row["app_type"],
            is_major=bool(row["is_major"]),
            is_eia=bool(row["is_eia"]),
            description=row["description"],
            address=row["address"],
            ward=row["ward"],
            applicant=row["applicant"],
            applicant_is_member_or_staff=bool(row["applicant_is_member_or_staff"]),
            councillor_call_in=bool(row["councillor_call_in"]),
            received=date.fromisoformat(row["received"]),
            validated=_d(row["validated"]),
            consultation_start=_d(row["consultation_start"]),
            extension_agreed_to=_d(row["extension_agreed_to"]),
            status=Status(row["status"]),
            case_officer=row["case_officer"],
        )

    def get(self, ref: str) -> Application:
        row = self._conn.execute("SELECT * FROM applications WHERE ref = ?", (ref,)).fetchone()
        if row is None:
            raise NotFound(f"no application {ref}")
        return self._app(row)

    def search(
        self,
        *,
        ward: str | None = None,
        status: Status | None = None,
        app_type: str | None = None,
        officer: str | None = None,
        open_only: bool = False,
        after_ref: str | None = None,
        limit: int = 20,
    ) -> list[Application]:
        """Keyset pagination on ref: stable under concurrent inserts, unlike OFFSET."""
        where: list[str] = []
        args: list[object] = []
        if ward:
            where.append("ward = ?")
            args.append(ward)
        if status:
            where.append("status = ?")
            args.append(status.value)
        if app_type:
            where.append("app_type = ?")
            args.append(app_type)
        if officer:
            where.append("case_officer = ?")
            args.append(officer)
        if open_only:
            where.append("status IN ('received','consultation','assessment')")
        if after_ref:
            where.append("ref > ?")
            args.append(after_ref)
        sql = "SELECT * FROM applications"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY ref LIMIT ?"
        args.append(limit)
        return [self._app(r) for r in self._conn.execute(sql, args)]

    def open_applications(self) -> list[Application]:
        return self.search(open_only=True, limit=1_000_000)

    def wards(self) -> list[str]:
        return [
            r[0] for r in self._conn.execute("SELECT DISTINCT ward FROM applications ORDER BY 1")
        ]

    def constraints(self, ref: str) -> list[Constraint]:
        rows = self._conn.execute("SELECT kind, detail FROM constraints WHERE ref = ?", (ref,))
        return [Constraint(kind=r["kind"], detail=r["detail"]) for r in rows]

    def consultees(self, ref: str) -> list[ConsulteeResponse]:
        rows = self._conn.execute(
            "SELECT consultee, response, summary FROM consultees WHERE ref = ? ORDER BY consultee",
            (ref,),
        )
        return [ConsulteeResponse(**dict(r)) for r in rows]

    def comments(self, ref: str) -> list[PublicComment]:
        rows = self._conn.execute(
            "SELECT * FROM comments WHERE ref = ? ORDER BY comment_id", (ref,)
        )
        return [
            PublicComment(
                comment_id=r["comment_id"],
                address=r["address"],
                stance=Stance(r["stance"]),
                text=r["text"],
                received=date.fromisoformat(r["received"]),
            )
            for r in rows
        ]

    def policy(self, policy_id: str) -> Policy:
        row = self._conn.execute(
            "SELECT * FROM policies WHERE policy_id = ?", (policy_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"no policy {policy_id}")
        return Policy(**dict(row))

    def policies(self) -> list[Policy]:
        return [Policy(**dict(r)) for r in self._conn.execute("SELECT * FROM policies ORDER BY 1")]

    def counts(self) -> dict[str, int]:
        out = {}
        for table in ("applications", "constraints", "consultees", "comments", "policies"):
            out[table] = int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        return out

    # ---- writes (only ever reached after human approval) --------------------------------

    def find_draft(self, idempotency_key: str) -> DecisionDraft | None:
        row = self._conn.execute(
            "SELECT * FROM drafts WHERE idempotency_key = ?", (idempotency_key,)
        ).fetchone()
        return self._draft(row) if row else None

    @staticmethod
    def _draft(row: sqlite3.Row) -> DecisionDraft:
        return DecisionDraft(
            draft_id=row["draft_id"],
            ref=row["ref"],
            recommendation=Recommendation(row["recommendation"]),
            reasons=json.loads(row["reasons"]),
            conditions=json.loads(row["conditions"]),
            route=row["route"],
            approved_by=row["approved_by"],
            created_at=row["created_at"],
            idempotency_key=row["idempotency_key"],
        )

    def save_draft(
        self,
        *,
        ref: str,
        recommendation: Recommendation,
        reasons: list[str],
        conditions: list[str],
        route: str,
        approved_by: str,
        idempotency_key: str,
    ) -> tuple[DecisionDraft, bool]:
        """Returns (draft, created). A repeated idempotency key returns the original draft."""
        existing = self.find_draft(idempotency_key)
        if existing:
            if existing.ref != ref:
                raise ValueError("idempotency key already used for a different application")
            return existing, False
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self.tx() as c:
            cur = c.execute(
                "INSERT INTO drafts (ref, recommendation, reasons, conditions, route, approved_by,"
                " created_at, idempotency_key) VALUES (?,?,?,?,?,?,?,?)",
                (
                    ref,
                    recommendation.value,
                    json.dumps(reasons),
                    json.dumps(conditions),
                    route,
                    approved_by,
                    now,
                    idempotency_key,
                ),
            )
            draft_id = cur.lastrowid
        row = self._conn.execute("SELECT * FROM drafts WHERE draft_id = ?", (draft_id,)).fetchone()
        return self._draft(row), True

    def drafts(self, ref: str | None = None) -> list[DecisionDraft]:
        if ref:
            rows = self._conn.execute("SELECT * FROM drafts WHERE ref = ?", (ref,))
        else:
            rows = self._conn.execute("SELECT * FROM drafts")
        return [self._draft(r) for r in rows]

    def record_extension(
        self, ref: str, new_date: date, reason: str, approved_by: str
    ) -> date | None:
        app = self.get(ref)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        with self.tx() as c:
            c.execute(
                "INSERT INTO extensions (ref, previous_date, new_date, reason, approved_by,"
                " created_at) VALUES (?,?,?,?,?,?)",
                (
                    ref,
                    app.extension_agreed_to.isoformat() if app.extension_agreed_to else None,
                    new_date.isoformat(),
                    reason,
                    approved_by,
                    now,
                ),
            )
            c.execute(
                "UPDATE applications SET extension_agreed_to = ? WHERE ref = ?",
                (new_date.isoformat(), ref),
            )
        return app.extension_agreed_to

    def audit(self, tool: str, args: dict[str, object], outcome: str) -> None:
        with self.tx() as c:
            c.execute(
                "INSERT INTO audit (at, tool, args, outcome) VALUES (?,?,?,?)",
                (
                    datetime.now(UTC).isoformat(timespec="seconds"),
                    tool,
                    json.dumps(args, sort_keys=True, default=str),
                    outcome,
                ),
            )

    def audit_log(self) -> list[dict[str, str]]:
        rows = self._conn.execute("SELECT tool, args, outcome FROM audit ORDER BY id")
        return [dict(r) for r in rows]
