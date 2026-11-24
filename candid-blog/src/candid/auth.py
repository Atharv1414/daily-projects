from functools import wraps
from urllib.parse import urlsplit

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func, select

from . import services, validation
from .extensions import db, limiter, login_manager
from .models import Role, User

bp = Blueprint("auth", __name__)


def role_required(*roles: Role):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def safe_next(target: str | None) -> str:
    """Only same-site paths, so a crafted link cannot redirect people to another site."""
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return url_for("blog.index")
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or any(ord(c) < 32 for c in target) or "\\" in target:
        return url_for("blog.index")
    return target


def login_key() -> str:
    return "login:" + request.form.get("username", "").strip().lower()[:30]


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    errors = {}
    if request.method == "POST":
        try:
            user = services.register_user(validation.registration(request.form.to_dict()))
        except validation.ValidationError as exc:
            errors = exc.errors
        else:
            session.clear()
            login_user(user)
            return redirect(url_for("blog.index"))
    return render_template("auth/register.html", errors=errors), 400 if errors else 200


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("20 per minute", methods=["POST"])
@limiter.limit("10 per 15 minutes", key_func=login_key, methods=["POST"])
def login():
    if request.method == "POST":
        user = services.authenticate(
            request.form.get("username", ""), request.form.get("password", "")
        )
        if user:
            session.clear()  # a new session on sign-in prevents session fixation
            login_user(user)
            session.permanent = True
            return redirect(safe_next(request.args.get("next")))
        flash("Wrong username or password.")
        return render_template("auth/login.html"), 401
    return render_template("auth/login.html")


@bp.post("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    return redirect(url_for("blog.index"))


@bp.get("/admin/users")
@role_required(Role.ADMIN)
def users():
    people = db.session.scalars(select(User).order_by(User.username)).all()
    return render_template("auth/users.html", people=people, roles=list(Role))


@bp.post("/admin/users/<int:user_id>")
@role_required(Role.ADMIN)
def update_user(user_id: int):
    user = db.get_or_404(User, user_id)
    role, active = request.form.get("role", ""), request.form.get("active") == "on"
    if role not in list(Role):
        abort(400, "Unknown role.")
    if user.role == Role.ADMIN and user.active and (role != Role.ADMIN or not active):
        admins = db.session.scalar(
            select(func.count()).where(User.role == Role.ADMIN.value, User.active)
        )
        if admins <= 1:
            abort(400, "The last active admin cannot be removed.")
    if user.role != role or user.active != active:
        user.session_version += 1
    user.role, user.active = role, active
    db.session.commit()
    flash(f"Updated {user.username}.")
    return redirect(url_for("auth.users"))
