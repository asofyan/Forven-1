import tempfile, pathlib, importlib
from fastapi.testclient import TestClient

def test_frontend_served_from_env_path(monkeypatch):
    tmp = tempfile.mkdtemp()
    pathlib.Path(tmp, "index.html").write_text("<h1>forven static</h1>")
    monkeypatch.setenv("FORVEN_FRONTEND_DIR", tmp)
    import forven.api as api
    importlib.reload(api)
    client = TestClient(api.app)
    r = client.get("/")
    assert r.status_code == 200
    assert "forven static" in r.text

def test_no_mount_when_env_unset(monkeypatch):
    monkeypatch.delenv("FORVEN_FRONTEND_DIR", raising=False)
    import forven.api as api
    importlib.reload(api)
    client = TestClient(api.app)
    r = client.get("/")
    assert "forven static" not in r.text
