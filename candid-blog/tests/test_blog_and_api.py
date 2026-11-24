from datetime import timedelta

import pytest
from conftest import PASSWORD, make_app
from flask_migrate import downgrade, upgrade
from sqlalchemy import inspect, select, text, update

from candid import services
from candid.extensions import db
from candid.markdown import render_markdown
from candid.models import ApiToken, now

POST = {"title": "Hello World", "body": "Some *text*", "tags": ["python"], "published": True}


def make(api, user="alan", **changes):
    response = api(user, "post", "/posts", json={**POST, **changes})
    assert response.status_code == 201, response.json
    return response.json["slug"]


def test_crud_through_the_api(api):
    created = api("alan", "post", "/posts", json=POST)
    assert created.headers["Location"].endswith("/api/v1/posts/hello-world")
    assert api(None, "get", "/posts/hello-world").json["tags"] == ["python"]
    changed = api(
        "alan", "put", "/posts/hello-world", json={**POST, "title": "New", "tags": ["a", "b"]}
    )
    assert changed.json["title"] == "New" and changed.json["tags"] == ["a", "b"]
    assert api("alan", "delete", "/posts/hello-world").status_code == 204
    assert api(None, "get", "/posts/hello-world").status_code == 404


@pytest.mark.parametrize("user,status", [(None, 401), ("rita", 403), ("alan", 201), ("ada", 201)])
def test_who_can_create(api, user, status):
    assert api(user, "post", "/posts", json=POST).status_code == status


@pytest.mark.parametrize(
    "user,status", [(None, 401), ("rita", 403), ("grace", 403), ("alan", 200), ("ada", 200)]
)
def test_who_can_edit(api, user, status):
    slug = make(api, "alan")
    assert api(user, "put", f"/posts/{slug}", json=POST).status_code == status


@pytest.mark.parametrize(
    "user,status", [(None, 404), ("rita", 404), ("grace", 404), ("alan", 200), ("ada", 200)]
)
def test_drafts_are_hidden(api, user, status):
    slug = make(api, "alan", published=False)
    assert api(user, "get", f"/posts/{slug}").status_code == status
    assert api(user, "get", "/posts?q=hello").json["total"] == (1 if status == 200 else 0)


@pytest.mark.parametrize(
    "change",
    [
        {"title": "ab"},
        {"title": "x" * 151},
        {"title": "two\nlines"},
        {"title": 5},
        {"body": ""},
        {"body": "nul\x00byte"},
        {"tags": "a b!"},
        {"tags": [1]},
        {"tags": [str(i) for i in range(9)]},
        {"published": "yes"},
    ],
)
def test_invalid_posts_are_rejected(api, change):
    response = api("alan", "post", "/posts", json={**POST, **change})
    assert response.status_code == 422
    assert set(response.json["error"]["fields"]) == set(change)


def test_malformed_requests_get_json_errors(api, client):
    assert api("alan", "post", "/posts", data="nope").status_code == 400
    assert api("alan", "post", "/posts", json=[1]).status_code == 400
    assert client.post("/api/v1/tokens", json={"username": 1}).status_code == 400
    assert client.get("/api/v1/nothing").json["error"]["code"] == 404
    big = api("alan", "post", "/posts", json={**POST, "body": "x" * 300_000})
    assert big.status_code in (400, 413)


def test_token_lifecycle(app, api, client):
    bad = client.post("/api/v1/tokens", json={"username": "alan", "password": "wrong"})
    assert bad.status_code == 401
    assert api("alan", "get", "/posts").status_code == 200
    with app.app_context():
        assert len(db.session.scalar(select(ApiToken)).digest) == 64
        db.session.execute(update(ApiToken).values(expires_at=now() - timedelta(seconds=1)))
        db.session.commit()
    assert api("alan", "get", "/posts").status_code == 401


def test_token_can_be_revoked(api):
    assert api("alan", "delete", "/tokens/current").status_code == 204
    assert api("alan", "get", "/posts").status_code == 401


def test_other_auth_schemes_are_refused(client):
    for header in ("Basic YTpi", "Bearer nope", "Bearer"):
        response = client.get("/api/v1/posts", headers={"Authorization": header})
        assert response.status_code == 401


def test_session_cookie_does_not_authenticate_the_api(login):
    """The API is exempt from CSRF checks, so it must never trust cookies."""
    assert login("ada").post("/api/v1/posts", json=POST).status_code == 401


def test_pagination(api):
    for i in range(12):
        make(api, title=f"Post number {i}")
    first = api(None, "get", "/posts?per_page=5").json
    assert (first["total"], first["pages"], len(first["items"])) == (12, 3, 5)
    assert len(api(None, "get", "/posts?per_page=5&page=3").json["items"]) == 2
    assert api(None, "get", "/posts?page=99").json["items"] == []
    assert len(api(None, "get", "/posts?per_page=9999&page=-4").json["items"]) == 12


def test_search_ranks_titles_first_and_stems_words(api):
    make(api, title="Cooking", body="I was running late")
    make(api, title="Running shoes", body="A review")
    titles = [p["title"] for p in api(None, "get", "/posts?q=run").json["items"]]
    assert titles == ["Running shoes", "Cooking"]


@pytest.mark.parametrize(
    "q", ['"', "a OR b", "title:x", "*", "'; DROP TABLE post;--", "NEAR(", "-"]
)
def test_search_syntax_is_never_interpreted(api, q):
    make(api)
    assert api(None, "get", "/posts", query_string={"q": q}).status_code == 200
    assert api(None, "get", "/posts").json["total"] == 1


def test_search_index_follows_edits_and_deletes(api):
    slug = make(api, body="aardvark")
    api("alan", "put", f"/posts/{slug}", json={**POST, "body": "zebra"})
    assert api(None, "get", "/posts?q=aardvark").json["total"] == 0
    assert api(None, "get", "/posts?q=zebra").json["total"] == 1
    api("alan", "delete", f"/posts/{slug}")
    assert api(None, "get", "/posts?q=zebra").json["total"] == 0


def test_tag_filter(api):
    make(api, title="First", tags=["flask"])
    make(api, title="Second", tags=["sql"])
    assert [p["title"] for p in api(None, "get", "/posts?tag=sql").json["items"]] == ["Second"]


def test_duplicate_titles_get_unique_slugs(api):
    assert make(api) != make(api)
    assert services.slugify("Crème Brûlée!") == "creme-brulee"
    assert services.slugify("日本") == "post"


@pytest.mark.parametrize(
    "source",
    [
        "<script>alert(1)</script>",
        "[x](javascript:alert(1))",
        '<img src=x onerror="alert(1)">',
        "[x](data:text/html,hi)",
    ],
)
def test_markdown_cannot_run_scripts(source):
    html = str(render_markdown(source)).lower()
    for bad in ("<script", "<img", 'href="javascript', 'href="data'):
        assert bad not in html


def test_web_pages(login, client):
    alan = login("alan")
    form = {"title": "My post", "body": "**bold**", "tags": "one, two", "published": "on"}
    response = alan.post("/posts/new", data=form)
    assert response.location == "/posts/my-post"
    page = client.get("/posts/my-post")
    assert b"<strong>bold</strong>" in page.data and b"Delete" not in page.data
    assert b"My post" in client.get("/?q=bold").data
    assert client.get("/?q=nothinghere").status_code == 200
    assert b"My post" in client.get("/?tag=one").data
    assert b'value="one, two"' in alan.get("/posts/my-post/edit").data
    assert alan.post("/posts/my-post/edit", data={**form, "title": ""}).status_code == 400
    assert alan.post("/posts/my-post/edit", data={**form, "title": "Edited"}).status_code == 302
    assert login("grace").get("/posts/my-post/edit").status_code == 403
    assert login("rita").get("/posts/new").status_code == 403
    assert alan.post("/posts/my-post/delete").status_code == 302
    assert client.get("/posts/my-post").status_code == 404


def test_comments(app, api, login):
    slug = make(api)
    rita = login("rita")
    rita.post(f"/posts/{slug}/comments", data={"body": "<b>hi</b>"})
    page = rita.get(f"/posts/{slug}").data
    assert b"&lt;b&gt;hi&lt;/b&gt;" in page
    rita.post(f"/posts/{slug}/comments", data={"body": " "})
    assert login("grace").post("/comments/1/delete").status_code == 403
    assert rita.post("/comments/1/delete").status_code == 302
    rita.post(f"/posts/{slug}/comments", data={"body": "again"})
    assert api("alan", "delete", f"/posts/{slug}").status_code == 204
    with app.app_context():
        assert db.session.scalar(text("SELECT count(*) FROM comment")) == 0


def test_health(client):
    assert client.get("/healthz").json == {"status": "ok"}


def test_unexpected_errors_hide_details(app, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(services, "list_posts", boom)
    client = app.test_client()
    for path in ("/", "/api/v1/posts"):
        response = client.get(path)
        assert response.status_code == 500
        assert b"secret detail" not in response.data


def test_migrations_build_the_same_schema_as_the_models(tmp_path):
    app = make_app(tmp_path)
    with app.app_context():
        upgrade()
        migrated = inspect(db.engine)
        for table in db.metadata.sorted_tables:
            assert {c["name"] for c in migrated.get_columns(table.name)} == set(table.c.keys())
        data = {"username": "ada", "email": "a@example.com", "password": PASSWORD}
        user = services.register_user(data)
        services.save_post(POST, user)
        assert services.list_posts(None, 1, "hello").total == 1
        db.session.remove()
        downgrade(revision="base")
        assert "post" not in inspect(db.engine).get_table_names()
