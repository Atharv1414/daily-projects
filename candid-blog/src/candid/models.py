import hashlib
import secrets
from datetime import UTC, datetime
from enum import StrEnum

import bcrypt
from flask import current_app
from flask_login import UserMixin
from sqlalchemy import CheckConstraint, ForeignKey, String, Text, event, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .extensions import db, login_manager


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Role(StrEnum):
    READER = "reader"
    AUTHOR = "author"
    ADMIN = "admin"


class User(UserMixin, db.Model):
    __tablename__ = "user"
    __table_args__ = (CheckConstraint("role IN ('reader','author','admin')", name="role"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(30), unique=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(60))
    role: Mapped[str] = mapped_column(String(10), default=Role.READER.value)
    active: Mapped[bool] = mapped_column(default=True)
    session_version: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(default=now)
    posts: Mapped[list["Post"]] = relationship(back_populates="author")

    @property
    def is_active(self) -> bool:
        return self.active

    def get_id(self) -> str:
        # Bumping session_version signs the user out everywhere.
        return f"{self.id}:{self.session_version}"

    def set_password(self, password: str) -> None:
        rounds = current_app.config["BCRYPT_ROUNDS"]
        self.password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds)).decode()

    def check_password(self, password: str) -> bool:
        raw = password.encode()
        return len(raw) <= 72 and bcrypt.checkpw(raw, self.password_hash.encode())

    @property
    def can_write(self) -> bool:
        return self.active and self.role in (Role.AUTHOR, Role.ADMIN)

    def can_edit(self, post: "Post") -> bool:
        return self.active and (
            self.role == Role.ADMIN or (self.can_write and post.author_id == self.id)
        )


class Post(db.Model):
    __tablename__ = "post"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(170), unique=True)
    body: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(default=now, onupdate=now)
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    author: Mapped[User] = relationship(back_populates="posts")
    tags: Mapped[list["Tag"]] = relationship(secondary="post_tag", order_by="Tag.name")
    comments: Mapped[list["Comment"]] = relationship(
        back_populates="post", cascade="all, delete-orphan", order_by="Comment.created_at"
    )


class Tag(db.Model):
    __tablename__ = "tag"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(30), unique=True)


class PostTag(db.Model):
    __tablename__ = "post_tag"
    post_id: Mapped[int] = mapped_column(
        ForeignKey("post.id", ondelete="CASCADE"), primary_key=True
    )
    tag_id: Mapped[int] = mapped_column(ForeignKey("tag.id"), primary_key=True, index=True)


class Comment(db.Model):
    __tablename__ = "comment"
    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=now)
    post_id: Mapped[int] = mapped_column(ForeignKey("post.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    post: Mapped[Post] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()


class ApiToken(db.Model):
    """Only a SHA-256 of the token is stored, so a leaked database reveals no usable tokens."""

    __tablename__ = "api_token"
    id: Mapped[int] = mapped_column(primary_key=True)
    digest: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime]
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"), index=True)
    user: Mapped[User] = relationship()

    @staticmethod
    def hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    @classmethod
    def issue(cls, user: User) -> str:
        token = secrets.token_urlsafe(32)
        expires = now() + current_app.config["TOKEN_LIFETIME"]
        db.session.add(cls(digest=cls.hash(token), expires_at=expires, user=user))
        return token


# Full-text index, kept in step with `post` by triggers so no code path can forget it.
FTS_STATEMENTS = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS post_fts USING fts5("
    "title, body, content='post', content_rowid='id', tokenize='porter unicode61')",
    "CREATE TRIGGER IF NOT EXISTS post_fts_insert AFTER INSERT ON post BEGIN "
    "INSERT INTO post_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END",
    "CREATE TRIGGER IF NOT EXISTS post_fts_delete AFTER DELETE ON post BEGIN "
    "INSERT INTO post_fts(post_fts, rowid, title, body) "
    "VALUES ('delete', old.id, old.title, old.body); END",
    "CREATE TRIGGER IF NOT EXISTS post_fts_update AFTER UPDATE OF title, body ON post BEGIN "
    "INSERT INTO post_fts(post_fts, rowid, title, body) "
    "VALUES ('delete', old.id, old.title, old.body); "
    "INSERT INTO post_fts(rowid, title, body) VALUES (new.id, new.title, new.body); END",
)


@event.listens_for(db.metadata, "after_create")
def _create_fts(_target, connection, **_kw) -> None:
    if connection.dialect.name == "sqlite":
        for statement in FTS_STATEMENTS:
            connection.execute(text(statement))


@login_manager.user_loader
def load_user(session_id: str) -> User | None:
    try:
        user_id, version = map(int, session_id.split(":"))
    except ValueError:
        return None
    user = db.session.get(User, user_id)
    return user if user and user.active and user.session_version == version else None
