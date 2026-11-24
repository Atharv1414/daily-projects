import pytest
from conftest import PASSWORD, csrf_from, make_app
from sqlalchemy import select

from candid import create_app
from candid.auth import safe_next
from candid.extensions import db
from candid.models import User


def user(name):
    return db.session.scalar(select(User).where(User.username == name))


def test_passwords_are_bcrypt_hashed(app):
    with app.app_context():
        assert user("ada").password_hash.startswith("$2b$")
        assert user("ada").check_password(PASSWORD)
        assert not user("ada").check_password("x" * 100)


def test_register_creates_a_reader_whatever_the_form_says(app, client):
    form = {
        "username": "new_user",
        "email": "New@Example.com",
        "password": PASSWORD,
        "role": "admin",
    }
    assert client.post("/register", data=form).status_code == 302
    with app.app_context():
        assert user("new_user").role == "reader"
        assert user("new_user").email == "new@example.com"


@pytest.mark.parametrize(
    "change",
    [
        {"username": "a"},
        {"username": "bad name"},
        {"username": "<script>"},
        {"email": "nope"},
        {"email": "a@b"},
        {"password": "short"},
        {"password": "é" * 40},
        {"password": "password1234"},
        {"username": "ADA"},
        {"email": "ada@example.com"},
    ],
)
def test_bad_registrations_are_rejected(client, change):
    form = {"username": "valid_name", "email": "v@example.com", "password": PASSWORD, **change}
    response = client.post("/register", data=form)
    assert response.status_code == 400
    assert b'role="alert"' in response.data


def test_login_and_logout(login):
    client = login("alan")
    assert b"Sign out alan" in client.get("/").data
    client.post("/logout")
    assert b"Sign in" in client.get("/").data


@pytest.mark.parametrize("name,password", [("alan", "wrong"), ("nobody", PASSWORD), ("", "")])
def test_failed_logins_look_the_same(client, name, password):
    response = client.post("/login", data={"username": name, "password": password})
    assert response.status_code == 401
    assert b"Wrong username or password." in response.data


@pytest.mark.parametrize(
    "target",
    ["//evil.com", "https://evil.com", "/\\evil.com", "javascript:alert(1)", "/a\\b", "/a\nb", ""],
)
def test_open_redirects_are_blocked(app, target):
    with app.test_request_context():
        assert safe_next(target) == "/"
        assert safe_next("/posts/new?a=1") == "/posts/new?a=1"


@pytest.mark.parametrize("name,status", [("rita", 403), ("alan", 403), ("ada", 200)])
def test_only_admins_see_users(login, name, status):
    assert login(name).get("/admin/users").status_code == status


def test_anonymous_is_sent_to_login(client):
    response = client.get("/admin/users")
    assert response.status_code == 302 and "/login" in response.location


def test_changing_a_role_signs_the_user_out_everywhere(app, login):
    rita, ada = login("rita"), login("ada")
    with app.app_context():
        rita_id = user("rita").id
    ada.post(f"/admin/users/{rita_id}", data={"role": "author", "active": "on"})
    assert b"Sign in" in rita.get("/").data
    assert login("rita").get("/posts/new").status_code == 200


def test_deactivated_users_cannot_use_site_or_api(app, api, login):
    assert api("rita", "get", "/posts").status_code == 200
    rita, ada = login("rita"), login("ada")
    with app.app_context():
        rita_id = user("rita").id
    ada.post(f"/admin/users/{rita_id}", data={"role": "reader"})
    assert b"Sign in" in rita.get("/").data
    assert api("rita", "get", "/posts").status_code == 401
    form = {"username": "rita", "password": PASSWORD}
    assert app.test_client().post("/login", data=form).status_code == 401


def test_the_last_admin_is_protected(app, login):
    ada = login("ada")
    with app.app_context():
        ada_id = user("ada").id
    assert ada.post(f"/admin/users/{ada_id}", data={"role": "reader"}).status_code == 400
    bad = {"role": "owner", "active": "on"}
    assert ada.post(f"/admin/users/{ada_id}", data=bad).status_code == 400


def test_csrf_is_enforced(tmp_path):
    app = make_app(tmp_path, WTF_CSRF_ENABLED=True)
    with app.app_context():
        db.create_all()
    client = app.test_client()
    form = {"username": "new_user", "email": "n@example.com", "password": PASSWORD}
    assert client.post("/register", data=form).status_code == 400
    token = csrf_from(client.get("/register").text)
    assert client.post("/register", data={**form, "csrf_token": token}).status_code == 302
    assert client.post("/logout").status_code == 400


def test_login_is_rate_limited_per_account(tmp_path):
    app = make_app(tmp_path, RATELIMIT_ENABLED=True)
    with app.app_context():
        db.create_all()
    client = app.test_client()
    form = {"username": "victim", "password": "guess"}
    codes = [client.post("/login", data=form).status_code for _ in range(11)]
    assert codes == [401] * 10 + [429]


def test_security_headers_and_cookie_flags(client):
    response = client.get("/login")
    assert "script-src 'none'" in response.headers["Content-Security-Policy"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    form = {"username": "ada", "password": PASSWORD}
    cookie = client.post("/login", data=form).headers["Set-Cookie"]
    assert "HttpOnly" in cookie and "SameSite=Lax" in cookie


def test_production_requires_a_secret_and_sets_secure_cookies(monkeypatch, tmp_path):
    monkeypatch.setenv("CANDID_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError):
        create_app()
    app = make_app(tmp_path)
    assert app.config["SESSION_COOKIE_SECURE"]
    with app.app_context():
        db.create_all()
    assert "Strict-Transport-Security" in app.test_client().get("/").headers


def test_create_user_command(app):
    runner = app.test_cli_runner()
    args = ["create-user", "boss", "boss@example.com", "--role", "admin", "--password", PASSWORD]
    assert runner.invoke(args=args).exit_code == 0
    assert runner.invoke(args=args).exit_code != 0  # already taken
    with app.app_context():
        assert user("boss").role == "admin"


def test_malformed_session_is_ignored(client):
    with client.session_transaction() as session:
        session["_user_id"] = "not-valid"
    assert client.get("/").status_code == 200
