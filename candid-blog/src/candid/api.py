"""JSON API, version 1. Authenticates with bearer tokens and ignores session cookies."""

from functools import wraps

from flask import Blueprint, abort, g, jsonify, request, url_for
from sqlalchemy import select

from . import services, validation
from .extensions import db, limiter
from .models import ApiToken, Post, User, now

bp = Blueprint("api", __name__, url_prefix="/api/v1")


def payload() -> dict:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        abort(400, "Send a JSON object.")
    return data


@bp.before_request
def load_token() -> None:
    g.user = g.token = None
    header = request.headers.get("Authorization", "")
    if not header:
        return
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer":
        abort(401, "Use a bearer token.")
    found = db.session.scalar(select(ApiToken).where(ApiToken.digest == ApiToken.hash(token)))
    if found is None or found.expires_at <= now() or not found.user.active:
        abort(401, "The token is invalid or has expired.")
    g.user, g.token = found.user, found


def token_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            abort(401, "Sign in first.")
        return view(*args, **kwargs)

    return wrapped


@bp.errorhandler(validation.ValidationError)
def invalid(error: validation.ValidationError):
    message = {"code": 422, "message": "Check the highlighted fields.", "fields": error.errors}
    return jsonify(error=message), 422


def as_json(post: Post) -> dict:
    return {
        "slug": post.slug,
        "title": post.title,
        "body": post.body,
        "published": post.published,
        "author": post.author.username,
        "tags": [t.name for t in post.tags],
        "created_at": post.created_at.isoformat() + "Z",
        "updated_at": post.updated_at.isoformat() + "Z",
    }


def find(slug: str, user: User | None) -> Post:
    return services.get_post(slug, user) or abort(404, "No such post.")


def find_editable(slug: str) -> Post:
    post = find(slug, g.user)
    if not g.user.can_edit(post):
        abort(403, "You cannot change this post.")
    return post


@bp.post("/tokens")
@limiter.limit("10 per minute")
def create_token():
    data = payload()
    username, password = data.get("username"), data.get("password")
    if not isinstance(username, str) or not isinstance(password, str):
        abort(400, "Send a username and password.")
    user = services.authenticate(username, password) or abort(401, "Wrong username or password.")
    token = ApiToken.issue(user)
    db.session.commit()
    return {"token": token}, 201


@bp.delete("/tokens/current")
@token_required
def revoke_token():
    db.session.delete(g.token)
    db.session.commit()
    return "", 204


@bp.get("/posts")
def list_posts():
    args = request.args
    page = services.list_posts(
        g.user,
        max(args.get("page", 1, type=int), 1),
        args.get("q", "")[:100],
        args.get("tag", "")[:30],
        min(max(args.get("per_page", 10, type=int), 1), 50),
    )
    return {
        "items": [as_json(p) for p in page.items],
        "page": page.page,
        "pages": page.pages,
        "total": page.total,
    }


@bp.get("/posts/<slug>")
def get_post(slug: str):
    return as_json(find(slug, g.user))


@bp.post("/posts")
@token_required
def create_post():
    if not g.user.can_write:
        abort(403, "Readers cannot write posts.")
    post = services.save_post(validation.post(payload()), g.user)
    return as_json(post), 201, {"Location": url_for("api.get_post", slug=post.slug)}


@bp.put("/posts/<slug>")
@token_required
def replace_post(slug: str):
    post = find_editable(slug)
    return as_json(services.save_post(validation.post(payload()), g.user, post))


@bp.delete("/posts/<slug>")
@token_required
def delete_post(slug: str):
    db.session.delete(find_editable(slug))
    db.session.commit()
    return "", 204
