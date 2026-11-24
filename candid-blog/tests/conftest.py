import re

import pytest

from candid import create_app, services
from candid.extensions import db
from candid.models import Role

PASSWORD = "correct-horse-battery"


def make_app(tmp_path, **overrides):
    return create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "test",
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{tmp_path / 'test.db'}",
            "BCRYPT_ROUNDS": 4,
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
            **overrides,
        }
    )


@pytest.fixture
def app(tmp_path):
    app = make_app(tmp_path)
    with app.app_context():
        db.create_all()
        for name, role in (
            ("ada", Role.ADMIN),
            ("alan", Role.AUTHOR),
            ("grace", Role.AUTHOR),
            ("rita", Role.READER),
        ):
            data = {"username": name, "email": f"{name}@example.com", "password": PASSWORD}
            services.register_user(data, role)
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(app):
    def _login(username, password=PASSWORD):
        client = app.test_client()
        response = client.post("/login", data={"username": username, "password": password})
        assert response.status_code == 302
        return client

    return _login


@pytest.fixture
def api(app):
    """api("alan", "post", "/posts", json=...) calls the API as that user."""
    tokens = {}

    def call(user, method, path, **kwargs):
        client = app.test_client()
        if user and user not in tokens:
            body = {"username": user, "password": PASSWORD}
            tokens[user] = client.post("/api/v1/tokens", json=body).json["token"]
        headers = {"Authorization": f"Bearer {tokens[user]}"} if user else {}
        return getattr(client, method)("/api/v1" + path, headers=headers, **kwargs)

    return call


def csrf_from(html: str) -> str:
    return re.search(r'name="csrf_token" value="([^"]+)"', html)[1]
