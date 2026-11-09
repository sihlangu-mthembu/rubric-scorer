"""SQLite database: connection per request, schema, and command-line helpers."""

import csv
import pathlib
import sqlite3

import click
from flask import current_app, g
from werkzeug.security import generate_password_hash

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    labels TEXT NOT NULL,                -- comma-separated rubric labels
    created_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
    prompt TEXT NOT NULL,
    response TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id),
    label TEXT NOT NULL,
    quality INTEGER NOT NULL CHECK (quality BETWEEN 1 AND 5),
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (item_id, user_id)            -- one score per reviewer per item
);
"""


def get_db() -> sqlite3.Connection:
    """One connection per request, stored on Flask's `g` and closed at the end."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.executescript(SCHEMA)
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def create_batch(name: str, labels: list[str], rows: list[dict], user_id: int) -> int:
    db = get_db()
    cur = db.execute("INSERT INTO batches (name, labels, created_by) VALUES (?, ?, ?)",
                     (name, ",".join(labels), user_id))
    batch_id = cur.lastrowid
    db.executemany("INSERT INTO items (batch_id, prompt, response) VALUES (?, ?, ?)",
                   [(batch_id, r["prompt"], r["response"]) for r in rows])
    db.commit()
    return batch_id


DEMO_CSV = pathlib.Path(__file__).parent / "demo_items.csv"
DEMO_LABELS = ["helpful", "unhelpful", "hallucination", "unsafe"]


@click.command("seed-demo")
@click.option("--admin", default="admin", help="Admin username to create")
@click.option("--password", prompt=True, hide_input=True, confirmation_prompt=True)
def seed_demo(admin: str, password: str) -> None:
    """Create an admin account and a demo batch of AI responses to score."""
    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE username = ?", (admin,)).fetchone()
    if existing:
        user_id = existing["id"]
    else:
        user_id = db.execute("INSERT INTO users (username, password_hash, is_admin) VALUES (?, ?, 1)",
                             (admin, generate_password_hash(password))).lastrowid
        db.commit()
    with DEMO_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    batch_id = create_batch("Demo: general knowledge answers", DEMO_LABELS, rows, user_id)
    click.echo(f"Created admin '{admin}' and demo batch {batch_id} with {len(rows)} items.")


def init_app(app) -> None:
    app.teardown_appcontext(close_db)
    app.cli.add_command(seed_demo)
