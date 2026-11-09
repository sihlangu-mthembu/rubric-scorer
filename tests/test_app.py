import io

import pytest

from rubric.metrics import cohens_kappa, pairwise_agreement

CSV = b"prompt,response\nQ1,A1\nQ2,A2\nQ3,A3\nQ4,A4\n"


def make_batch(actions, csv_bytes=CSV, labels="good, bad"):
    return actions.post(
        "/batches/new",
        {"name": "Test batch", "labels": labels, "file": (io.BytesIO(csv_bytes), "items.csv")},
        content_type="multipart/form-data",
    )


def score(actions, item_id, label, quality=4, rationale="Clear and accurate answer."):
    return actions.post(f"/batches/items/{item_id}", {"label": label, "quality": quality, "rationale": rationale})


# --- authentication ------------------------------------------------------------------

def test_login_required(client):
    r = client.get("/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_first_user_is_admin_and_second_is_not(actions, client):
    actions.register("alice")
    actions.register("bob")
    actions.login("bob")
    assert client.get("/batches/new").status_code == 403
    actions.logout()
    actions.login("alice")
    assert client.get("/batches/new").status_code == 200


def test_duplicate_username_and_weak_password_rejected(actions):
    actions.register("alice")
    assert b"already taken" in actions.register("alice").data
    assert b"at least 8" in actions.register("carol", password="short").data


def test_wrong_password_rejected(actions, client):
    actions.register("alice")
    actions.login("alice", "wrong-password")
    assert client.get("/").status_code == 302


def test_post_without_csrf_token_is_rejected(client):
    assert client.post("/auth/login", data={"username": "x", "password": "y"}).status_code == 400


def test_open_redirect_blocked(actions):
    actions.register("alice")
    token = actions.token()
    r = actions.client.post("/auth/login?next=//evil.example.com",
                            data={"username": "alice", "password": "password123", "csrf_token": token})
    assert r.headers["Location"] == "/"


# --- batches and scoring -----------------------------------------------------------------

def test_admin_creates_batch_from_csv(actions, client):
    actions.register("alice")
    actions.login("alice")
    r = make_batch(actions)
    assert r.status_code == 302
    page = client.get(r.headers["Location"]).get_data(as_text=True)
    assert page.count("not scored") == 4


def test_bad_csv_is_rejected_with_message(actions, client):
    actions.register("alice")
    actions.login("alice")
    make_batch(actions, b"question,answer\nQ,A\n")
    assert b"prompt" in client.get("/batches/new").data


def test_scoring_moves_to_next_item_and_validates(actions):
    actions.register("alice")
    actions.login("alice")
    make_batch(actions)
    r = score(actions, 1, "good")
    assert r.headers["Location"].endswith("/batches/items/2")
    assert b"Choose one of the rubric labels" in score(actions, 2, "not-a-label").data
    assert b"between 1 and 5" in score(actions, 2, "good", quality=9).data
    assert b"at least 10" in score(actions, 2, "good", rationale="ok").data


def test_rescoring_updates_instead_of_duplicating(actions, client):
    actions.register("alice")
    actions.login("alice")
    make_batch(actions)
    score(actions, 1, "good")
    score(actions, 1, "bad")
    csv_text = client.get("/batches/1/export.csv").get_data(as_text=True)
    assert csv_text.count("\n") == 2  # header + one row
    assert ",bad," in csv_text


def test_results_show_agreement_and_disagreements(actions, client):
    actions.register("alice")
    actions.register("bob")
    actions.login("alice")
    make_batch(actions)
    for item, label in zip([1, 2, 3, 4], ["good", "good", "bad", "bad"], strict=True):
        score(actions, item, label)
    actions.logout()
    actions.login("bob")
    for item, label in zip([1, 2, 3, 4], ["good", "bad", "bad", "bad"], strict=True):
        score(actions, item, label)
    actions.logout()
    actions.login("alice")
    page = client.get("/batches/1/results").get_data(as_text=True)
    assert "alice vs bob" in page and "75%" in page
    assert "<td>4</td>" in page and "built-in method" not in page
    assert "Disagreements to adjudicate (1)" in page


def test_reviewer_cannot_see_results_or_export(actions, client):
    actions.register("alice")
    actions.register("bob")
    actions.login("alice")
    make_batch(actions)
    actions.logout()
    actions.login("bob")
    assert client.get("/batches/1/results").status_code == 403
    assert client.get("/batches/1/export.csv").status_code == 403


def test_export_neutralises_spreadsheet_formulas(actions, client):
    actions.register("alice")
    actions.login("alice")
    make_batch(actions, b'prompt,response\n"=HYPERLINK(""http://x"")",A\nQ2,A2\n')
    score(actions, 1, "good")
    csv_text = client.get("/batches/1/export.csv").get_data(as_text=True)
    assert "'=HYPERLINK" in csv_text


def test_html_in_responses_is_escaped(actions, client):
    actions.register("alice")
    actions.login("alice")
    make_batch(actions, b"prompt,response\n<script>alert(1)</script>,A\nQ2,A2\n")
    page = client.get("/batches/items/1").get_data(as_text=True)
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page


# --- metrics -------------------------------------------------------------------------------

def test_kappa_perfect_and_chance():
    assert cohens_kappa(["a", "b", "a", "b"], ["a", "b", "a", "b"]) == pytest.approx(1.0)
    assert cohens_kappa(["a", "a", "b", "b"], ["a", "b", "a", "b"]) == pytest.approx(0.0)


def test_pairwise_skips_pairs_with_too_few_shared_items():
    assert pairwise_agreement({"x": {1: "a"}, "y": {1: "a"}}) == []
