import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(forven_db):
    from forven.api import app
    return TestClient(app)


def test_get_default_cap_returns_5(client):
    r = client.get("/api/deepdive/cost-cap")
    assert r.status_code == 200
    assert r.json() == {"cap_usd": 5.0}


def test_set_cap_persists_and_read_returns_it(client):
    r = client.put("/api/deepdive/cost-cap", json={"cap_usd": 10.5})
    assert r.status_code == 200
    assert r.json() == {"cap_usd": 10.5}
    r2 = client.get("/api/deepdive/cost-cap")
    assert r2.json() == {"cap_usd": 10.5}


def test_set_negative_cap_rejected(client):
    r = client.put("/api/deepdive/cost-cap", json={"cap_usd": -1.0})
    assert r.status_code == 400


def test_set_zero_cap_allowed(client):
    """Zero is a legitimate way to disable deepdive."""
    r = client.put("/api/deepdive/cost-cap", json={"cap_usd": 0})
    assert r.status_code == 200
    assert r.json() == {"cap_usd": 0.0}
