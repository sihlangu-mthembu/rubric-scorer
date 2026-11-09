"""Batches of AI responses: create, score, review agreement, export."""

import csv
import io

from flask import Blueprint, Response, abort, flash, g, redirect, render_template, request, url_for

from .auth import admin_required, login_required
from .db import create_batch, get_db
from .metrics import pairwise_agreement

bp = Blueprint("batches", __name__, url_prefix="/batches")

MAX_ITEMS = 500


@login_required
def index():
    """Dashboard: every batch with the current user's progress."""
    rows = get_db().execute(
        """
        SELECT b.id, b.name, b.created_at,
               (SELECT COUNT(*) FROM items i WHERE i.batch_id = b.id) AS total,
               (SELECT COUNT(*) FROM scores s JOIN items i ON s.item_id = i.id
                 WHERE i.batch_id = b.id AND s.user_id = ?) AS done
        FROM batches b ORDER BY b.id DESC
        """,
        (g.user["id"],),
    ).fetchall()
    return render_template("index.html", batches=rows)


def _get_batch(batch_id: int):
    batch = get_db().execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None:
        abort(404)
    return batch


def parse_items_csv(text: str) -> list[dict]:
    """Read a CSV with `prompt` and `response` columns; raise ValueError with a clear message."""
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or not {"prompt", "response"} <= {f.strip().lower() for f in reader.fieldnames}:
        raise ValueError("The CSV needs a header row with 'prompt' and 'response' columns.")
    rows = []
    for row in reader:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        if row.get("prompt") and row.get("response"):
            rows.append({"prompt": row["prompt"], "response": row["response"]})
    if not rows:
        raise ValueError("No rows with both a prompt and a response were found.")
    if len(rows) > MAX_ITEMS:
        raise ValueError(f"Batches are limited to {MAX_ITEMS} items.")
    return rows


@bp.route("/new", methods=("GET", "POST"))
@admin_required
def new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        labels = [x.strip() for x in request.form.get("labels", "").split(",") if x.strip()]
        upload = request.files.get("file")
        try:
            if not name:
                raise ValueError("Give the batch a name.")
            if len(labels) < 2 or len(set(labels)) != len(labels):
                raise ValueError("Enter at least two distinct labels, separated by commas.")
            if upload is None or not upload.filename:
                raise ValueError("Choose a CSV file to upload.")
            rows = parse_items_csv(upload.read().decode("utf-8-sig"))
        except UnicodeDecodeError:
            flash("The file must be UTF-8 text (save it as 'CSV UTF-8').")
        except ValueError as e:
            flash(str(e))
        else:
            batch_id = create_batch(name, labels, rows, g.user["id"])
            flash(f"Created batch with {len(rows)} items.")
            return redirect(url_for("batches.view", batch_id=batch_id))
    return render_template("batches/new.html")


@bp.route("/<int:batch_id>")
@login_required
def view(batch_id: int):
    batch = _get_batch(batch_id)
    items = get_db().execute(
        """SELECT i.id, i.prompt, s.label, s.quality
           FROM items i LEFT JOIN scores s ON s.item_id = i.id AND s.user_id = ?
           WHERE i.batch_id = ? ORDER BY i.id""",
        (g.user["id"], batch_id),
    ).fetchall()
    return render_template("batches/view.html", batch=batch, items=items)


@bp.route("/items/<int:item_id>", methods=("GET", "POST"))
@login_required
def score(item_id: int):
    db = get_db()
    item = db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    if item is None:
        abort(404)
    batch = _get_batch(item["batch_id"])
    labels = batch["labels"].split(",")
    existing = db.execute("SELECT * FROM scores WHERE item_id = ? AND user_id = ?",
                          (item_id, g.user["id"])).fetchone()

    if request.method == "POST":
        label = request.form.get("label")
        rationale = request.form.get("rationale", "").strip()
        try:
            quality = int(request.form.get("quality", ""))
        except ValueError:
            quality = 0
        if label not in labels:
            flash("Choose one of the rubric labels.")
        elif not 1 <= quality <= 5:
            flash("Quality must be between 1 and 5.")
        elif len(rationale) < 10:
            flash("Write a rationale of at least 10 characters.")
        else:
            # Insert or, if this reviewer already scored the item, update their score.
            db.execute(
                """INSERT INTO scores (item_id, user_id, label, quality, rationale) VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT (item_id, user_id) DO UPDATE SET
                     label = excluded.label, quality = excluded.quality,
                     rationale = excluded.rationale, created_at = CURRENT_TIMESTAMP""",
                (item_id, g.user["id"], label, quality, rationale),
            )
            db.commit()
            nxt = db.execute(
                """SELECT i.id FROM items i
                   WHERE i.batch_id = ? AND i.id NOT IN (SELECT item_id FROM scores WHERE user_id = ?)
                   ORDER BY i.id LIMIT 1""",
                (batch["id"], g.user["id"]),
            ).fetchone()
            if nxt:
                return redirect(url_for("batches.score", item_id=nxt["id"]))
            flash("Batch complete. Thank you!")
            return redirect(url_for("batches.view", batch_id=batch["id"]))

    return render_template("batches/score.html", item=item, batch=batch, labels=labels, existing=existing)


def _scores(batch_id: int):
    return get_db().execute(
        """SELECT i.id AS item_id, i.prompt, i.response, u.username, s.label, s.quality, s.rationale, s.created_at
           FROM scores s JOIN items i ON s.item_id = i.id JOIN users u ON s.user_id = u.id
           WHERE i.batch_id = ? ORDER BY i.id, u.username""",
        (batch_id,),
    ).fetchall()


@bp.route("/<int:batch_id>/results")
@admin_required
def results(batch_id: int):
    batch = _get_batch(batch_id)
    rows = _scores(batch_id)
    by_reviewer: dict[str, dict[int, str]] = {}
    by_item: dict[int, dict] = {}
    for r in rows:
        by_reviewer.setdefault(r["username"], {})[r["item_id"]] = r["label"]
        entry = by_item.setdefault(r["item_id"], {"prompt": r["prompt"], "labels": {}})
        entry["labels"][r["username"]] = r["label"]

    label_counts = {label: 0 for label in batch["labels"].split(",")}
    for r in rows:
        label_counts[r["label"]] = label_counts.get(r["label"], 0) + 1

    disagreements = [
        {"item_id": iid, **info} for iid, info in by_item.items()
        if len(info["labels"]) > 1 and len(set(info["labels"].values())) > 1
    ]
    return render_template(
        "batches/results.html", batch=batch, reviewers=sorted(by_reviewer),
        pairs=pairwise_agreement(by_reviewer), label_counts=label_counts,
        disagreements=disagreements, total_scores=len(rows),
    )


def _safe_cell(value):
    """Stop spreadsheet formula injection: Excel runs cells starting with = + - @ as formulas."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


@bp.route("/<int:batch_id>/export.csv")
@admin_required
def export(batch_id: int):
    batch = _get_batch(batch_id)
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["item_id", "prompt", "response", "reviewer", "label", "quality", "rationale", "scored_at"])
    for r in _scores(batch_id):
        writer.writerow([_safe_cell(v) for v in (r["item_id"], r["prompt"], r["response"], r["username"],
                                                  r["label"], r["quality"], r["rationale"], r["created_at"])])
    filename = f"batch-{batch['id']}-scores.csv"
    return Response(out.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})
