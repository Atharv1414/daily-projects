"""Allow-list input validation, shared by the HTML forms and the JSON API."""

import re
import unicodedata

USERNAME = re.compile(r"[A-Za-z0-9_]{3,30}")
EMAIL = re.compile(r"[^@\s]{1,64}@[^@\s.]+(\.[^@\s.]+)+")
TAG = re.compile(r"[a-z0-9][a-z0-9-]{0,29}")
COMMON_PASSWORDS = {"password1234", "123456789012", "qwertyuiop12", "letmein12345"}


class ValidationError(ValueError):
    def __init__(self, errors: dict[str, str]) -> None:
        super().__init__("; ".join(errors.values()))
        self.errors = errors


def _text(data: dict, key: str) -> str:
    value = data.get(key)
    return unicodedata.normalize("NFC", value).strip() if isinstance(value, str) else ""


def has_control(value: str) -> bool:
    return any(unicodedata.category(c) == "Cc" and c not in "\n\r\t" for c in value)


def registration(data: dict) -> dict[str, str]:
    username, email = _text(data, "username"), _text(data, "email").lower()
    password = data.get("password")
    errors = {}
    if not USERNAME.fullmatch(username):
        errors["username"] = "Username must be 3-30 letters, numbers or underscores."
    if len(email) > 254 or not EMAIL.fullmatch(email) or has_control(email):
        errors["email"] = "Enter a valid email address."
    if not isinstance(password, str) or len(password) < 12:
        errors["password"] = "Password must be at least 12 characters."
    elif len(password.encode()) > 72:
        errors["password"] = "Password is too long (72 bytes at most)."  # bcrypt's limit
    elif password.lower() in COMMON_PASSWORDS or password.lower() == username.lower():
        errors["password"] = "That password is too easy to guess."
    if errors:
        raise ValidationError(errors)
    return {"username": username, "email": email, "password": password}


def post(data: dict) -> dict:
    title, body, errors = _text(data, "title"), _text(data, "body"), {}
    if not 3 <= len(title) <= 150 or has_control(title) or "\n" in title:
        errors["title"] = "Title must be 3-150 characters on one line."
    if not 1 <= len(body) <= 50_000 or has_control(body):
        errors["body"] = "Body must be 1-50,000 characters."
    raw = data.get("tags", [])
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list) or not all(isinstance(t, str) for t in raw):
        raw, errors["tags"] = [], "Tags must be a list of words."
    tags = sorted({t.strip().lower() for t in raw if t.strip()})
    if len(tags) > 8 or not all(TAG.fullmatch(t) for t in tags):
        errors["tags"] = "Use up to 8 tags of letters, numbers and hyphens."
    published = data.get("published", False)
    if not isinstance(published, bool):
        errors["published"] = "Published must be true or false."
    if errors:
        raise ValidationError(errors)
    return {"title": title, "body": body, "tags": tags, "published": published}


def comment(data: dict) -> str:
    body = _text(data, "body")
    if not 1 <= len(body) <= 2000 or has_control(body):
        raise ValidationError({"body": "Comment must be 1-2,000 characters."})
    return body
