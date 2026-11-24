from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from . import services, validation
from .auth import role_required
from .extensions import db, limiter
from .models import Comment, Post, Role

bp = Blueprint("blog", __name__)


def viewer():
    return current_user if current_user.is_authenticated else None


def find(slug: str) -> Post:
    # 404 rather than 403, so a hidden draft's existence is not revealed.
    return services.get_post(slug, viewer()) or abort(404)


def find_editable(slug: str) -> Post:
    post = find(slug)
    if not current_user.can_edit(post):
        abort(403)
    return post


@bp.get("/")
def index():
    search, tag = request.args.get("q", "")[:100], request.args.get("tag", "")[:30]
    page = services.list_posts(viewer(), max(request.args.get("page", 1, type=int), 1), search, tag)
    return render_template("index.html", page=page, search=search, tag=tag)


@bp.get("/posts/<slug>")
def show(slug: str):
    return render_template("post.html", post=find(slug))


def form_data() -> dict:
    return {**request.form.to_dict(), "published": request.form.get("published") == "on"}


def edit_page(post: Post | None):
    errors = {}
    if request.method == "POST":
        try:
            saved = services.save_post(validation.post(form_data()), current_user, post)
        except validation.ValidationError as exc:
            errors = exc.errors
        else:
            return redirect(url_for("blog.show", slug=saved.slug))
    return render_template("edit.html", post=post, errors=errors), 400 if errors else 200


@bp.route("/posts/new", methods=["GET", "POST"])
@role_required(Role.AUTHOR, Role.ADMIN)
def new():
    return edit_page(None)


@bp.route("/posts/<slug>/edit", methods=["GET", "POST"])
@login_required
def edit(slug: str):
    return edit_page(find_editable(slug))


@bp.post("/posts/<slug>/delete")
@login_required
def delete(slug: str):
    db.session.delete(find_editable(slug))
    db.session.commit()
    flash("Post deleted.")
    return redirect(url_for("blog.index"))


@bp.post("/posts/<slug>/comments")
@login_required
@limiter.limit("10 per minute")
def comment(slug: str):
    post = find(slug)
    try:
        body = validation.comment(request.form.to_dict())
    except validation.ValidationError as exc:
        flash(str(exc))
    else:
        db.session.add(Comment(body=body, post=post, author=current_user))
        db.session.commit()
    return redirect(url_for("blog.show", slug=slug))


@bp.post("/comments/<int:comment_id>/delete")
@login_required
def delete_comment(comment_id: int):
    item = db.get_or_404(Comment, comment_id)
    if current_user.role != Role.ADMIN and item.author_id != current_user.id:
        abort(403)
    slug = item.post.slug
    db.session.delete(item)
    db.session.commit()
    return redirect(url_for("blog.show", slug=slug))


@bp.get("/healthz")
@limiter.exempt
def health():
    db.session.execute(db.text("SELECT 1"))
    return {"status": "ok"}
