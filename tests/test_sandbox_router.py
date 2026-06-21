"""Phase 2 (P2-T09) — /api/sandbox router tests.

Asserts:
- GET  /api/sandbox/runs paginates, filters (strategy_id, kind, timed_out).
- GET  /api/sandbox/runs/{id} returns full row + parsed JSON columns; 404.
- POST /api/sandbox/scan runs AST guard, returns AstReport, persists scan row.
- POST /api/sandbox/scan returns 404 when path missing, 400 when not file.
- POST /api/sandbox/scan is available even when sandbox_enabled=False.
- POST /api/sandbox/test runs hello-world end-to-end (only when enabled).
- POST /api/sandbox/runs/{id}/kill 404s for unknown, 409s for completed,
  succeeds when registered as active.
- All non-/scan endpoints 503 when sandbox_enabled=False.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from forven.api import app
from forven.db import get_db
from forven.routers import sandbox as sandbox_router


def _enable_sandbox(monkeypatch) -> None:
    monkeypatch.setattr(
        "forven.sandbox.strategy_adapter.get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 30},
    )
    # Router imports get_sandbox_config from strategy_adapter, but its
    # _require_enabled() reads through the module-level binding. Patch both.
    monkeypatch.setattr(
        sandbox_router, "get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 30},
    )


def _disable_sandbox(monkeypatch) -> None:
    monkeypatch.setattr(
        sandbox_router, "get_sandbox_config",
        lambda: {"enabled": False, "mem_mb": 256, "cpu_s": 30, "wall_s": 30},
    )


def _seed_run(
    *,
    strategy_id: str | None = None,
    kind: str = "run",
    timed_out: int = 0,
    exit_code: int = 0,
    error: str | None = None,
    ast_findings_json: str | None = None,
) -> int:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO sandbox_runs
            (strategy_id, kind, started_at, ended_at, exit_code, timed_out,
             ast_findings_json, error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (strategy_id, kind, now, now, exit_code, timed_out,
             ast_findings_json, error),
        )
        return int(cur.lastrowid)


# --------------------------------------------------------------------------- #
# GET /api/sandbox/runs                                                        #
# --------------------------------------------------------------------------- #


def test_list_runs_returns_envelope(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    _seed_run(strategy_id="S00001")
    _seed_run(strategy_id="S00001")
    _seed_run(strategy_id="S00002")

    r = TestClient(app).get("/api/sandbox/runs")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["rows"]) == 3
    assert body["limit"] == 50
    assert body["offset"] == 0


def test_list_runs_filters_by_strategy_id(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    _seed_run(strategy_id="S00001")
    _seed_run(strategy_id="S00002")
    _seed_run(strategy_id="S00002")

    r = TestClient(app).get("/api/sandbox/runs?strategy_id=S00002")
    body = r.json()
    assert body["total"] == 2
    assert all(row["strategy_id"] == "S00002" for row in body["rows"])


def test_list_runs_filters_by_kind(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    _seed_run(kind="scan", error="ast_block", exit_code=-1)
    _seed_run(kind="run")
    _seed_run(kind="run")

    r = TestClient(app).get("/api/sandbox/runs?kind=scan")
    body = r.json()
    assert body["total"] == 1
    assert body["rows"][0]["kind"] == "scan"


def test_list_runs_filters_by_timed_out(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    _seed_run(timed_out=0)
    _seed_run(timed_out=1, exit_code=124)

    r = TestClient(app).get("/api/sandbox/runs?timed_out=true")
    body = r.json()
    assert body["total"] == 1
    assert body["rows"][0]["timed_out"] == 1


def test_list_runs_pagination(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    for _ in range(5):
        _seed_run()

    r = TestClient(app).get("/api/sandbox/runs?limit=2&offset=0")
    body = r.json()
    assert body["total"] == 5
    assert len(body["rows"]) == 2

    r = TestClient(app).get("/api/sandbox/runs?limit=2&offset=4")
    body = r.json()
    assert len(body["rows"]) == 1


def test_list_runs_503_when_disabled(forven_db, monkeypatch):
    _disable_sandbox(monkeypatch)
    r = TestClient(app).get("/api/sandbox/runs")
    assert r.status_code == 503
    assert r.json()["detail"]["error"] == "sandbox_disabled"


# --------------------------------------------------------------------------- #
# GET /api/sandbox/runs/{run_id}                                               #
# --------------------------------------------------------------------------- #


def test_get_run_returns_full_row_with_parsed_findings(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    findings = '[{"kind":"forbidden_import","lineno":1,"col":0,"message":"x","node_repr":"y"}]'
    rid = _seed_run(kind="scan", error="ast_block", exit_code=-1,
                    ast_findings_json=findings)

    r = TestClient(app).get(f"/api/sandbox/runs/{rid}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == rid
    assert body["error"] == "ast_block"
    assert body["ast_findings"] is not None
    assert body["ast_findings"][0]["kind"] == "forbidden_import"
    assert body["security_events"] is None
    assert body["active"] is False


def test_get_run_404_for_unknown(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    r = TestClient(app).get("/api/sandbox/runs/9999999")
    assert r.status_code == 404


def test_get_run_503_when_disabled(forven_db, monkeypatch):
    _disable_sandbox(monkeypatch)
    rid = _seed_run()
    r = TestClient(app).get(f"/api/sandbox/runs/{rid}")
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# POST /api/sandbox/scan  (always available)                                   #
# --------------------------------------------------------------------------- #


CLEAN_SOURCE = "def generate_signal(ohlcv):\n    return {'trades': [], 'stats': {}}\n"
DIRTY_SOURCE = "import os\n\ndef generate_signal(ohlcv):\n    return {}\n"


def test_scan_clean_returns_ok(forven_db, monkeypatch, tmp_path):
    _enable_sandbox(monkeypatch)
    f = tmp_path / "clean.py"
    f.write_text(CLEAN_SOURCE, encoding="utf-8")

    r = TestClient(app).post("/api/sandbox/scan", json={"path": str(f)})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["findings"] == []
    assert body["row_id"] is not None


def test_scan_blocked_returns_findings(forven_db, monkeypatch, tmp_path):
    _enable_sandbox(monkeypatch)
    f = tmp_path / "dirty.py"
    f.write_text(DIRTY_SOURCE, encoding="utf-8")

    r = TestClient(app).post("/api/sandbox/scan", json={"path": str(f)})
    body = r.json()
    assert body["ok"] is False
    assert any(f["kind"] == "forbidden_import" for f in body["findings"])


def test_scan_persists_scan_row(forven_db, monkeypatch, tmp_path):
    _enable_sandbox(monkeypatch)
    f = tmp_path / "dirty.py"
    f.write_text(DIRTY_SOURCE, encoding="utf-8")
    TestClient(app).post("/api/sandbox/scan", json={"path": str(f)})

    with get_db() as conn:
        rows = list(conn.execute(
            "SELECT * FROM sandbox_runs WHERE kind='scan'"
        ))
    assert len(rows) == 1
    assert rows[0]["error"] == "ast_block"


def test_scan_404_for_missing_path(forven_db, monkeypatch, tmp_path):
    _enable_sandbox(monkeypatch)
    r = TestClient(app).post(
        "/api/sandbox/scan", json={"path": str(tmp_path / "nope.py")}
    )
    assert r.status_code == 404


def test_scan_400_for_directory(forven_db, monkeypatch, tmp_path):
    _enable_sandbox(monkeypatch)
    r = TestClient(app).post("/api/sandbox/scan", json={"path": str(tmp_path)})
    assert r.status_code == 400


def test_scan_works_when_sandbox_disabled(forven_db, monkeypatch, tmp_path):
    """AST scan is read-only — must work even with sandbox_enabled=False."""
    _disable_sandbox(monkeypatch)
    f = tmp_path / "clean.py"
    f.write_text(CLEAN_SOURCE, encoding="utf-8")
    r = TestClient(app).post("/api/sandbox/scan", json={"path": str(f)})
    assert r.status_code == 200
    assert r.json()["ok"] is True


# --------------------------------------------------------------------------- #
# POST /api/sandbox/test                                                       #
# --------------------------------------------------------------------------- #


def test_post_test_runs_hello_world(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    r = TestClient(app).post("/api/sandbox/test")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["exit_code"] == 0
    assert body["timed_out"] is False
    assert body["stdout_payload"] is not None
    assert body["stdout_payload"]["stats"]["hello"] == "world"


def test_post_test_503_when_disabled(forven_db, monkeypatch):
    _disable_sandbox(monkeypatch)
    r = TestClient(app).post("/api/sandbox/test")
    assert r.status_code == 503


# --------------------------------------------------------------------------- #
# POST /api/sandbox/runs/{run_id}/kill                                         #
# --------------------------------------------------------------------------- #


def test_kill_404_for_unknown_run(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    r = TestClient(app).post("/api/sandbox/runs/9999999/kill")
    assert r.status_code == 404


def test_kill_409_for_completed_run(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    rid = _seed_run()  # row exists but not in _ACTIVE_RUNS
    r = TestClient(app).post(f"/api/sandbox/runs/{rid}/kill")
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "run_not_active"


def test_kill_succeeds_for_active_run(forven_db, monkeypatch):
    _enable_sandbox(monkeypatch)
    rid = _seed_run()
    killed = {"called": False}

    def _killer():
        killed["called"] = True

    sandbox_router.register_active_run(rid, kill_callable=_killer)
    try:
        r = TestClient(app).post(f"/api/sandbox/runs/{rid}/kill")
        assert r.status_code == 200
        assert r.json()["killed"] is True
        assert killed["called"] is True
        # After successful kill the run should be removed from the registry.
        assert rid not in sandbox_router._ACTIVE_RUNS
    finally:
        sandbox_router.unregister_active_run(rid)


def test_kill_503_when_disabled(forven_db, monkeypatch):
    _disable_sandbox(monkeypatch)
    rid = _seed_run()
    r = TestClient(app).post(f"/api/sandbox/runs/{rid}/kill")
    assert r.status_code == 503
