"""Registration, login and logout. Passwords are stored only as salted hashes."""

import functools
import sqlite3

from flask import Blueprint, abort, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone() if user_id else None


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    @login_required
    def wrapped(**kwargs):
        if not g.user["is_admin"]:
            abort(403)
        return view(**kwargs)
    return wrapped


@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        error = None
        if not (3 <= len(username) <= 30) or not username.replace("_", "").isalnum():
            error = "Username must be 3–30 letters, numbers or underscores."
        elif len(password) < 8:
            error = "Password must be at least 8 characters."
        if error is None:
            db = get_db()
            # The very first account becomes the admin.
            is_admin = db.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
            try:
                db.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, ?)",
                           (username, generate_password_hash(password), int(is_admin)))
                db.commit()
            except sqlite3.IntegrityError:
                error = f"Username {username} is already taken."
            else:
                flash("Account created. Please log in.")
                return redirect(url_for("auth.login"))
        flash(error)
    return render_template("auth/register.html")


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = get_db().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        # Same message for unknown user and wrong password, so attackers can't probe usernames.
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Incorrect username or password.")
        else:
            token = session.get("csrf_token")
            session.clear()                       # new session on login prevents session fixation
            session["user_id"] = user["id"]
            if token:
                session["csrf_token"] = token
            # Only follow `next` if it is a path on this site; otherwise a crafted link could
            # send the user to another website after login (an "open redirect").
            next_url = request.args.get("next", "")
            is_local = next_url.startswith("/") and not next_url.startswith("//")
            return redirect(next_url if is_local else url_for("index"))
    return render_template("auth/login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
