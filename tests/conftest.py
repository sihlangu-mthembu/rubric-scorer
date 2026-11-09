import re

import pytest

from rubric import create_app


@pytest.fixture()
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db"), "SECRET_KEY": "test"})


@pytest.fixture()
def client(app):
    return app.test_client()


class Actions:
    """Helpers that act like a user in the browser, including the CSRF token every form needs."""

    def __init__(self, client):
        self.client = client

    def token(self, path="/auth/login"):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="csrf_token" value="([0-9a-f]+)"', html).group(1)

    def post(self, path, data=None, **kwargs):
        data = dict(data or {})
        data.setdefault("csrf_token", self.token())
        return self.client.post(path, data=data, **kwargs)

    def register(self, username, password="password123"):
        return self.post("/auth/register", {"username": username, "password": password})

    def login(self, username, password="password123"):
        return self.post("/auth/login", {"username": username, "password": password})

    def logout(self):
        return self.post("/auth/logout")


@pytest.fixture()
def actions(client):
    return Actions(client)
