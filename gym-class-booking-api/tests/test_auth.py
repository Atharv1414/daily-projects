from .conftest import PASSWORD, login


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "version": "1.0.0"}


def test_register_login_and_me(client):
    resp = client.post(
        "/auth/register", json={"email": "Aisha@Members.Example", "full_name": "Aisha", "password": PASSWORD}
    )
    assert resp.status_code == 201
    assert resp.json()["email"] == "aisha@members.example"
    assert "password" not in resp.text and "hash" not in resp.text
    me = client.get("/me", headers=login(client, "aisha@members.example")).json()
    assert me["role"] == "member"


def test_duplicate_email_is_rejected(client, member):
    member("Ben")
    resp = client.post(
        "/auth/register", json={"email": "BEN@members.example", "full_name": "Ben", "password": PASSWORD}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "email_taken"


def test_weak_password_and_bad_email_fail_validation(client):
    assert (
        client.post(
            "/auth/register", json={"email": "x@y.io", "full_name": "X", "password": "short"}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/auth/register", json={"email": "nope", "full_name": "X", "password": PASSWORD}
        ).status_code
        == 422
    )


def test_wrong_password_gives_generic_401(client, member):
    member("Chloe")
    for email in ("chloe@members.example", "nobody@members.example"):
        resp = client.post("/auth/login", json={"email": email, "password": "not-the-password"})
        assert resp.status_code == 401
        assert resp.json()["error"]["message"] == "Incorrect email or password"
        assert resp.headers["WWW-Authenticate"] == "Bearer"


def test_protected_routes_need_a_valid_token(client):
    assert client.get("/classes").status_code == 401
    assert client.get("/classes", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_expired_token_is_rejected(client, member, clock):
    headers = member("Dev")
    clock.advance(minutes=61)
    resp = client.get("/me", headers=headers)
    assert resp.status_code == 401
    assert "expired" in resp.json()["error"]["message"]


def test_members_cannot_use_staff_routes(client, member, make_class):
    gym_class = make_class()
    headers = member("Ella")
    assert client.post("/classes", json={}, headers=headers).status_code in (403, 422)
    assert client.get(f"/classes/{gym_class['id']}/roster", headers=headers).status_code == 403
    assert client.get("/reports/utilisation", headers=headers).json()["error"]["code"] == "forbidden"
