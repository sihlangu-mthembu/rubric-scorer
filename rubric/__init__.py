"""Rubric Scorer: a small full-stack web app where reviewers label AI responses against a rubric,
and an admin sees inter-reviewer agreement and exports the results."""

import os
import secrets

from flask import Flask, abort, request, session


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-me"),
        DATABASE=os.environ.get("RUBRIC_DB", os.path.join(app.instance_path, "rubric.db")),
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,  # reject uploads over 2 MB
        ADMIN_USERNAME=os.environ.get("ADMIN_USERNAME", "admin"),
        ADMIN_PASSWORD=os.environ.get("ADMIN_PASSWORD"),
        SEED_DEMO=os.environ.get("SEED_DEMO", "") == "1",
    )
    if test_config:
        app.config.update(test_config)
    os.makedirs(app.instance_path, exist_ok=True)

    from . import auth, batches, db

    db.init_app(app)
    app.register_blueprint(auth.bp)
    app.register_blueprint(batches.bp)
    app.add_url_rule("/", endpoint="index", view_func=batches.index)

    # --- CSRF protection -------------------------------------------------------------
    # Every form includes a random token stored in the user's session. A POST without
    # the matching token is rejected, so another website cannot submit forms as the user.
    @app.before_request
    def check_csrf():
        if request.method == "POST":
            token = session.get("csrf_token")
            if not token or token != request.form.get("csrf_token"):
                abort(400, "Missing or invalid CSRF token")

    @app.context_processor
    def inject_csrf():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_hex(16)
        return {"csrf_token": session["csrf_token"]}

    return app
