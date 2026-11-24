"""Business rules shared by the web pages and the API."""

import re
import secrets
import unicodedata
from functools import lru_cache

import bcrypt
from flask import current_app
from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import joinedload, selectinload

from .extensions import db
from .models import Post, Role, Tag, User
from .validation import ValidationError

PER_PAGE = 10


def register_user(data: dict[str, str], role: Role = Role.READER) -> User:
    user = User(username=data["username"], email=data["email"], role=role.value)
    user.set_password(data["password"])
    taken = ValidationError({"username": "That username or email is already in use."})
    clash = select(User.id).where(
        or_(func.lower(User.username) == user.username.lower(), User.email == user.email)
    )
    if db.session.scalar(clash):
        raise taken
    db.session.add(user)
    try:
        db.session.commit()
    except IntegrityError:  # lost a race with another sign-up
        db.session.rollback()
        raise taken from None
    return user


@lru_cache(maxsize=4)
def _dummy_hash(rounds: int) -> bytes:
    return bcrypt.hashpw(b"not-a-real-password", bcrypt.gensalt(rounds))


def authenticate(username: str, password: str) -> User | None:
    user = db.session.scalar(
        select(User).where(func.lower(User.username) == username.strip().lower())
    )
    if user is None:
        # Spend the same time as a real check, so response times do not reveal usernames.
        bcrypt.checkpw(password.encode()[:72], _dummy_hash(current_app.config["BCRYPT_ROUNDS"]))
        return None
    return user if user.check_password(password) and user.active else None


def slugify(title: str) -> str:
    ascii_title = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_title.lower()).strip("-")[:150] or "post"


def _unique_slug(title: str) -> str:
    slug = slugify(title)
    if db.session.scalar(select(Post.id).where(Post.slug == slug)):
        slug = f"{slug}-{secrets.token_hex(4)}"
    return slug


def _tags(names: list[str]) -> list[Tag]:
    found = {t.name: t for t in db.session.scalars(select(Tag).where(Tag.name.in_(names)))}
    return [found.get(name) or Tag(name=name) for name in names]


def save_post(data: dict, author: User, post: Post | None = None) -> Post:
    if post is None:
        post = Post(author=author, slug=_unique_slug(data["title"]))
        db.session.add(post)
    post.title, post.body, post.published = data["title"], data["body"], data["published"]
    with db.session.no_autoflush:
        post.tags = _tags(data["tags"])
    db.session.commit()
    return post


def visible(user: User | None):
    """Drafts are visible only to their author and to admins."""
    query = select(Post).options(joinedload(Post.author), selectinload(Post.tags))
    if user is None:
        return query.where(Post.published)
    if user.role == Role.ADMIN:
        return query
    return query.where(or_(Post.published, Post.author_id == user.id))


def get_post(slug: str, user: User | None) -> Post | None:
    return db.session.scalar(visible(user).where(Post.slug == slug))


def fts_query(search: str) -> str:
    """Quote each word so user input can never be read as FTS5 query syntax."""
    words = re.findall(r"\w+", search, re.UNICODE)[:10]
    return " ".join(f'"{w}"' for w in words)


def list_posts(user: User | None, page: int, search: str = "", tag: str = "", per_page=PER_PAGE):
    query = visible(user)
    if tag:
        query = query.where(Post.tags.any(Tag.name == tag.lower()))
    if search.strip():
        match = fts_query(search)
        if not match:
            query = query.where(text("0"))
        else:
            ranked = (
                text(
                    "SELECT rowid AS id, bm25(post_fts, 5.0, 1.0) AS score FROM post_fts "
                    "WHERE post_fts MATCH :match"
                )  # fmt: skip
                .bindparams(match=match)
                .columns(Post.id, score=db.Float)
                .subquery("ranked")
            )
            query = query.join(ranked, ranked.c.id == Post.id).order_by(ranked.c.score)
    query = query.order_by(Post.created_at.desc(), Post.id.desc())
    return db.paginate(query, page=page, per_page=per_page, max_per_page=50, error_out=False)
