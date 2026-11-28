import sqlite3

import pytest

from planning_casework_mcp.datagen import FIXTURE_REFS, build_store
from planning_casework_mcp.domain import Recommendation, Status
from planning_casework_mcp.store import SCHEMA_VERSION, CaseStore, NotFound


def test_generator_is_seeded_and_messy(tmp_path):
    a = build_store(str(tmp_path / "a.db"), n=400, seed=3)
    b = build_store(str(tmp_path / "b.db"), n=400, seed=3)
    assert a.counts() == b.counts()
    assert a.counts()["applications"] == 400 + len(FIXTURE_REFS)
    statuses = {x.status for x in a.search(limit=10_000)}
    assert {Status.RECEIVED, Status.ASSESSMENT, Status.APPROVED} <= statuses
    # Messiness the tools must cope with: missing publicity dates and repeated comments.
    apps = a.search(limit=10_000)
    assert any(x.validated and x.consultation_start is None for x in apps)
    texts = [(c.address.strip().lower(), c.text) for x in apps for c in a.comments(x.ref)]
    assert len(texts) > len(set(texts))


def test_migrations_are_versioned_and_idempotent(tmp_path):
    path = tmp_path / "m.db"
    s = CaseStore(path)
    assert s.schema_version() == SCHEMA_VERSION
    s.close()
    again = CaseStore(path)  # re-opening must not re-run migrations
    assert again.schema_version() == SCHEMA_VERSION


def test_keyset_pagination_has_no_gaps_or_repeats(store):
    seen, cursor = [], None
    while True:
        page = store.search(after_ref=cursor, limit=37)
        if not page:
            break
        seen += [a.ref for a in page]
        cursor = page[-1].ref
    assert seen == sorted(seen) and len(seen) == len(set(seen)) == store.counts()["applications"]


def test_drafts_are_idempotent(store):
    kwargs = dict(
        ref="26/00733/ADV",
        recommendation=Recommendation.APPROVE,
        reasons=[],
        conditions=[],
        route="delegated",
        approved_by="Officer",
        idempotency_key="key-1",
    )
    first, created = store.save_draft(**kwargs)
    second, created_again = store.save_draft(**kwargs)
    assert created and not created_again and first.draft_id == second.draft_id
    with pytest.raises(ValueError, match="different application"):
        store.save_draft(**{**kwargs, "ref": "26/00417/HOU"})
    assert len(store.drafts()) == 1


def test_foreign_keys_enforced(store):
    with pytest.raises(sqlite3.IntegrityError):
        store.save_draft(
            ref="26/99999/HOU",
            recommendation=Recommendation.APPROVE,
            reasons=[],
            conditions=[],
            route="delegated",
            approved_by="x",
            idempotency_key="k2",
        )


def test_not_found(store):
    with pytest.raises(NotFound):
        store.get("26/99999/HOU")
