from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from law_firm_profitability_bi import cli, export
from law_firm_profitability_bi.api import create_app
from law_firm_profitability_bi.config import AccessDenied, Settings
from law_firm_profitability_bi.security import issue_token, verify_token

KEY = "unit-test-signing-value"


@pytest.fixture(scope="module")
def client(con):
    return TestClient(create_app(con, Settings(signing_key=KEY)))


def auth(user: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {issue_token(user, KEY, 60)}"}


def test_token_round_trip():
    assert verify_token(issue_token("mp", KEY, 60), KEY).user_id == "mp"


@pytest.mark.parametrize("token", ["", "a", "a.b", "a.b.c", "!!.zz", "é.x"])
def test_garbage_tokens_are_refused(token):
    with pytest.raises(AccessDenied):
        verify_token(token, KEY)


def test_tampered_foreign_and_expired_tokens_are_refused():
    token = issue_token("head_disputes", KEY, 60)
    payload, signature = token.split(".")
    other = issue_token("mp", KEY, 60).split(".")[0]
    for bad in (f"{other}.{signature}", issue_token("mp", "another", 60)):
        with pytest.raises(AccessDenied):
            verify_token(bad, KEY)
    with pytest.raises(AccessDenied, match="expired"):
        verify_token(issue_token("mp", KEY, 60, now=0), KEY, now=61)
    assert payload


def test_app_refuses_an_empty_key(con):
    with pytest.raises(ValueError, match="signing key"):
        create_app(con, Settings(signing_key=""))


@pytest.mark.parametrize(
    "path",
    ["/", "/api/kpis", "/api/units", "/api/lockup", "/api/waterfall", "/api/variance",
     "/api/lifecycle", "/api/matters", "/api/catalogue"],
)  # fmt: skip
def test_endpoints_need_sign_in_and_work(client, path):
    assert client.get(path).status_code == 401
    assert client.get(path, headers=auth("finance")).status_code == 200


def test_scope_is_enforced_over_http(client):
    for path in ("/", "/api/kpis", "/api/matters", "/api/lifecycle", "/api/variance"):
        response = client.get(path, params={"unit": "CORP"}, headers=auth("head_disputes"))
        assert response.status_code == 403
        assert response.json() == {"detail": "not permitted"}


def test_unknown_and_forbidden_units_look_the_same(client):
    a = client.get("/api/kpis", params={"unit": "CORP"}, headers=auth("head_disputes"))
    b = client.get("/api/kpis", params={"unit": "ZZZ"}, headers=auth("head_disputes"))
    assert (a.status_code, a.json()) == (b.status_code, b.json())


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/kpis", {"start": "2026-01-15"}),
        ("/api/kpis", {"start": "nonsense"}),
        ("/api/matters", {"size": 1000}),
        ("/api/matters", {"sort": "password"}),
        ("/", {"month": "2019-01-01"}),
    ],
)
def test_bad_input_is_422(client, path, params):
    assert client.get(path, params=params, headers=auth("mp")).status_code == 422


def test_restatement_endpoint(client):
    params = {"month": "2026-04-01", "reported_on": "2026-04-30", "restated_on": "2026-10-31"}
    steps = client.get("/api/restatement", params=params, headers=auth("mp")).json()
    assert steps[0]["step"] == "As reported" and steps[-1]["step"] == "Restated"


def test_login_sets_a_cookie(con):
    with TestClient(create_app(con, Settings(signing_key=KEY))) as fresh:
        assert fresh.get("/login", params={"token": "bad.token"}).status_code == 401
        token = issue_token("head_realestate", KEY, 60)
        page = fresh.get("/login", params={"token": token})
        assert page.status_code == 200
        assert "<h1>Real Estate</h1>" in page.text
        assert token not in page.text


def test_page_shows_only_the_users_units(client):
    page = client.get("/", headers=auth("head_disputes")).text
    assert "Construction" in page
    assert "Employment" not in page and "Private Client" not in page


def test_page_numbers_match_the_api(client):
    kpis = client.get("/api/kpis", headers=auth("mp")).json()
    page = client.get("/", headers=auth("mp")).text
    assert f"£{kpis['billed'] / 1e6:,.2f}m" in page


def test_static_export(con, tmp_path):
    assert export.write_validation(con, tmp_path / "v.md")
    pages = export.export_dashboards(con, tmp_path / "dash")
    charts = export.export_charts(con, tmp_path / "charts")
    assert len(pages) == 2 and len(charts) == 4
    assert all(p.stat().st_size > 2000 for p in pages + charts)


def test_cli_build_validate_and_report(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LAWBI_DATABASE", str(tmp_path / "t.duckdb"))
    assert cli.main(["validate"]) == 1
    assert "law-bi build" in capsys.readouterr().err
    assert cli.main(["build"]) == 0
    assert cli.main(["validate"]) == 0
    assert cli.main(["kpis", "--user", "head_disputes", "--unit", "CORP"]) == 1
    assert cli.main(["restate", "--unit", "EMP"]) == 0
    assert "Late posted" in capsys.readouterr().out
