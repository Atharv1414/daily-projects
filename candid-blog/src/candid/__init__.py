"""Candid: a small, secure blog. `create_app` wires models, views and controllers together."""

import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import api, auth, blog, commands
from .extensions import csrf, db, limiter, login_manager, migrate
from .markdown import render_markdown
from .models import Role

CSP = (
    "default-src 'self'; script-src 'none'; img-src 'self' https:; object-src 'none'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


def create_app(config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    production = os.environ.get("CANDID_ENV", "development") == "production"
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", ""),
        SQLALCHEMY_DATABASE_URI=os.environ.get(
            "DATABASE_URL", f"sqlite:///{Path(app.instance_path) / 'candid.db'}"
        ),
        MAX_CONTENT_LENGTH=256 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=production,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        BCRYPT_ROUNDS=12,
        RATELIMIT_STORAGE_URI=os.environ.get("RATELIMIT_STORAGE_URI", "memory://"),
        TOKEN_LIFETIME=timedelta(days=30),
    )
    app.config.update(config or {})
    if app.instance_path in app.config["SQLALCHEMY_DATABASE_URI"]:
        Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.config["SECRET_KEY"]:
        if production:
            raise RuntimeError("Set SECRET_KEY before running in production.")
        app.config["SECRET_KEY"] = secrets.token_hex(32)  # sessions reset on restart
    if hops := int(os.environ.get("TRUSTED_PROXIES", "0")):
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops)

    db.init_app(app)
    migrate.init_app(app, db, directory=str(Path(__file__).parent / "migrations"))
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(blog.bp)
    app.register_blueprint(api.bp)
    csrf.exempt(api.bp)  # the API uses bearer tokens only, never cookies
    commands.register(app)
    app.jinja_env.filters["markdown"] = render_markdown
    app.jinja_env.globals["Role"] = Role

    @app.after_request
    def security_headers(response):
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if production:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/"):
            return jsonify(error={"code": error.code, "message": error.description}), error.code
        return render_template("error.html", error=error), error.code

    @app.errorhandler(Exception)
    def unexpected(error):
        app.logger.exception("unhandled error")
        db.session.rollback()
        if request.path.startswith("/api/"):
            return jsonify(error={"code": 500, "message": "Something went wrong."}), 500
        return render_template("error.html", error=None), 500

    return app
