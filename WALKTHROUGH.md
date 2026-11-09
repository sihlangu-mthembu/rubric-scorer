# Walkthrough

Read this before any interview where this project might come up.

## The big picture

This is a **server-rendered** web app: the browser asks for a page, Flask runs Python to fetch data from the database, fills an HTML template, and sends back the finished page. Forms send data back with POST requests. (Project 3, yield-curve-web, is the other style: a single-page app where the browser builds the page with JavaScript.)

## `rubric/__init__.py`: the app factory

- `create_app()` builds and configures the Flask app. Using a **factory** lets tests create a fresh app with its own temporary database.
- **Blueprints** (`auth`, `batches`) group related routes into separate files.
- **CSRF protection:** `inject_csrf` puts a random token in the session and in every form. `check_csrf` rejects any POST whose token doesn't match. A malicious website can make your browser send a POST to this app, but it can't read your token, so the forged request fails.

## `rubric/db.py`: the database

- Four tables: `users`, `batches`, `items`, `scores`. `REFERENCES` creates foreign keys; `ON DELETE CASCADE` removes a batch's items and scores with it.
- `UNIQUE (item_id, user_id)` guarantees one score per reviewer per item. The scoring route uses `INSERT ... ON CONFLICT DO UPDATE` (an **upsert**) so re-scoring updates the existing row.
- `CHECK (quality BETWEEN 1 AND 5)` enforces the range in the database itself, as a second line of defence behind the form validation.
- `get_db()` opens one connection per request and stores it on Flask's `g`; `close_db` closes it when the request ends.
- `seed-demo` is a custom **CLI command** (`flask --app rubric seed-demo`) that creates an admin and a demo batch.

## `rubric/auth.py`: accounts

- `generate_password_hash` / `check_password_hash`: passwords are **hashed with a salt**, so even someone who steals the database can't read them.
- `load_logged_in_user` runs before every request and puts the current user on `g.user`.
- `login_required` and `admin_required` are **decorators**: wrappers that check access before the real view runs (redirect to login, or 403 Forbidden).
- On login, `session.clear()` creates a fresh session (prevents **session fixation**), and the `next` URL is only followed if it is a local path (prevents an **open redirect**).
- The same error message for "no such user" and "wrong password" stops attackers discovering which usernames exist.

## `rubric/batches.py`: the main features

- `index`: one SQL query with **subqueries** counts each batch's items and the current user's scores for the progress bars.
- `parse_items_csv`: reads the upload with `csv.DictReader`, checks the required columns and limits, and raises `ValueError` with a message the user can act on.
- `score`: validates input, saves with an upsert, then finds the next unscored item with `NOT IN (SELECT ...)`.
- `results`: groups scores by reviewer and by item, then calls `pairwise_agreement` from `metrics.py`.
- `export`: writes CSV in memory and returns it with a `Content-Disposition: attachment` header so the browser downloads it. `_safe_cell` neutralises **formula injection**: a cell like `=HYPERLINK(...)` would otherwise run as a formula when opened in Excel.

## `rubric/metrics.py`: agreement

- **Percent agreement:** share of shared items where two reviewers chose the same label.
- **Cohen's kappa:** `(observed - expected) / (1 - expected)`, where *expected* is the agreement you'd get by chance given how often each reviewer uses each label. 1 is perfect, 0 is chance.
- `pairwise_agreement` compares every pair of reviewers (`itertools.combinations`) on the items both scored.

## `rubric/templates/`: the pages

Jinja templates. `base.html` holds the shared layout; other pages use `{% extends %}` and fill `{% block content %}`. Jinja **escapes** everything inserted with `{{ }}`, so a response containing `<script>` is shown as text, not run (this is tested).

## `tests/`

17 pytest tests. `conftest.py` creates a fresh app and database per test, and an `Actions` helper that behaves like a user: it reads the CSRF token from a page before every form submission. Tests cover login and roles, CSRF, open redirects, CSV validation, scoring and re-scoring, agreement results, access control, formula injection, XSS escaping and the kappa maths.

## Deployment

`bootstrap()` in `db.py` runs at start-up: if `ADMIN_PASSWORD` is set it creates the admin account (and, with `SEED_DEMO`, the demo batch). This matters on free hosting, where the database starts empty after every restart: without it, whoever registered first after a restart would become admin. A test checks that a stranger registering first stays a reviewer.


`Dockerfile` runs the app with **gunicorn**, a production web server (Flask's built-in server is for development only). The database lives in `/data` so it can be put on a persistent volume.

## Ideas to extend it yourself

1. Let the admin mark an adjudicated "gold" label for each disagreement.
2. Add per-reviewer accuracy against those gold labels.
3. Add a time-per-item measure to spot rushed reviews.
4. Swap SQLite for Postgres for multi-server deployments.
