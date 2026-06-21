"""Tests for forven.diagnostics — health checks + snapshot."""

from datetime import datetime, timedelta, timezone

from click.testing import CliRunner

from forven.cli import cli
from forven.db import get_db
from forven.diagnostics import (
    FAIL,
    PASS,
    WARN,
    check_database,
    check_recent_costs,
    check_recent_truncations,
    check_resumable_tasks,
    check_scheduler_freshness,
    snapshot,
)
from forven.task_progress import mark_interrupted


def _create_task(*, status: str, display_id: str, cost_usd: float = 0.0,
                 total_tokens: int = 0, completed_at: str | None = None) -> int:
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO agent_tasks
               (agent_id, display_id, title, description, type, status,
                started_at, completed_at, cost_usd, total_tokens)
               VALUES (?, ?, ?, '', 'general', ?, '2026-04-25T00:00:00+00:00',
                       ?, ?, ?)""",
            ("agent-test", display_id, "test", status, completed_at, cost_usd, total_tokens),
        )
        return int(cursor.lastrowid)


def test_check_database_passes_after_init(forven_db):
    result = check_database()
    assert result.status == PASS
    assert "schema" in result.summary


def test_check_database_does_not_run_init(monkeypatch, forven_db):
    def _boom():
        raise AssertionError("diagnostics must not initialize schema")

    monkeypatch.setattr("forven.db.init_db", _boom)
    result = check_database()
    assert result.status == PASS


def test_check_resumable_tasks_pass_when_none(forven_db):
    result = check_resumable_tasks()
    assert result.status == PASS
    assert result.detail["count"] == 0


def test_check_resumable_tasks_warn_when_present(forven_db):
    task_id = _create_task(status="running", display_id="T99300")
    mark_interrupted([task_id])
    result = check_resumable_tasks()
    assert result.status == WARN
    assert result.detail["count"] == 1


def test_check_recent_costs_aggregates(forven_db):
    now = datetime.now(timezone.utc).isoformat()
    _create_task(status="done", display_id="T99301",
                 cost_usd=0.05, total_tokens=1000, completed_at=now)
    _create_task(status="done", display_id="T99302",
                 cost_usd=0.10, total_tokens=2000, completed_at=now)
    result = check_recent_costs(window_hours=24)
    assert result.status == PASS
    assert abs(result.detail["cost_usd"] - 0.15) < 1e-6
    assert result.detail["total_tokens"] == 3000
    assert result.detail["task_count"] == 2


def test_check_recent_costs_outside_window_excluded(forven_db):
    old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _create_task(status="done", display_id="T99303",
                 cost_usd=99.99, total_tokens=99999, completed_at=old)
    result = check_recent_costs(window_hours=24)
    assert result.detail["cost_usd"] == 0.0
    assert result.detail["task_count"] == 0


def test_check_recent_truncations_zero(forven_db):
    result = check_recent_truncations()
    assert result.status == PASS
    assert result.detail["count_24h"] == 0


def test_check_scheduler_freshness_warn_when_no_runs(forven_db):
    result = check_scheduler_freshness()
    assert result.status == WARN


def test_snapshot_aggregates(forven_db):
    payload = snapshot()
    assert "generated_at" in payload
    assert "overall" in payload
    assert payload["overall"] in {PASS, WARN, FAIL}
    assert "checks" in payload and len(payload["checks"]) >= 5
    summary = payload["summary"]
    assert sum(summary.values()) == len(payload["checks"])


def test_snapshot_overall_warn_with_resumable(forven_db):
    """One WARN check should make overall WARN (no FAILs present)."""
    task_id = _create_task(status="running", display_id="T99304")
    mark_interrupted([task_id])
    payload = snapshot()
    assert payload["overall"] in {WARN, FAIL}


def test_doctor_cli_runs_and_returns_json(forven_db):
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor", "--json"])
    # Exit code 0 (PASS/WARN) or 2 (FAIL) — both are "ran cleanly"
    assert result.exit_code in (0, 2)
    import json
    payload = json.loads(result.output)
    assert "checks" in payload
    assert "overall" in payload


def test_doctor_cli_human_output(forven_db):
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code in (0, 2)
    assert "forven doctor" in result.output


# --------------------------------------------------------------------------- #
# P2-T10 — check_sandbox_status                                                #
# --------------------------------------------------------------------------- #


def _seed_sandbox_run(
    *, kind: str = "run", exit_code: int = 0, timed_out: int = 0,
    error: str | None = None,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO sandbox_runs
               (kind, started_at, ended_at, exit_code, timed_out, error)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (kind, now, now, exit_code, timed_out, error),
        )


def test_check_sandbox_status_warns_when_disabled(forven_db, monkeypatch):
    from forven.diagnostics import WARN, check_sandbox_status

    monkeypatch.setattr(
        "forven.sandbox.strategy_adapter.get_sandbox_config",
        lambda: {"enabled": False, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    r = check_sandbox_status()
    assert r.status == WARN
    assert r.detail["enabled"] is False


def test_check_sandbox_status_passes_when_enabled_no_runs(forven_db, monkeypatch):
    from forven.diagnostics import PASS, check_sandbox_status

    monkeypatch.setattr(
        "forven.sandbox.strategy_adapter.get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    r = check_sandbox_status()
    assert r.status == PASS
    assert r.detail["enabled"] is True
    assert r.detail["sample_size"] == 0


def test_check_sandbox_status_passes_with_healthy_history(forven_db, monkeypatch):
    from forven.diagnostics import PASS, check_sandbox_status

    monkeypatch.setattr(
        "forven.sandbox.strategy_adapter.get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    for _ in range(10):
        _seed_sandbox_run(exit_code=0, timed_out=0)
    r = check_sandbox_status()
    assert r.status == PASS
    assert r.detail["success_rate"] == 1.0


def test_check_sandbox_status_warns_on_high_timeout_rate(forven_db, monkeypatch):
    from forven.diagnostics import WARN, check_sandbox_status

    monkeypatch.setattr(
        "forven.sandbox.strategy_adapter.get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    # 4 timed out + 6 clean = 40% timeout rate (> 20% threshold)
    for _ in range(4):
        _seed_sandbox_run(exit_code=124, timed_out=1)
    for _ in range(6):
        _seed_sandbox_run(exit_code=0, timed_out=0)
    r = check_sandbox_status()
    assert r.status == WARN
    assert "timed out" in r.summary
    assert r.detail["timeout_rate"] >= 0.4


def test_check_sandbox_status_warns_on_low_success_rate(forven_db, monkeypatch):
    from forven.diagnostics import WARN, check_sandbox_status

    monkeypatch.setattr(
        "forven.sandbox.strategy_adapter.get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    # 7 crashes + 3 successes = 30% success rate (< 80% threshold), no timeouts
    for _ in range(7):
        _seed_sandbox_run(exit_code=1, timed_out=0, error="runtime")
    for _ in range(3):
        _seed_sandbox_run(exit_code=0, timed_out=0)
    r = check_sandbox_status()
    assert r.status == WARN
    assert r.detail["success_rate"] == 0.3


def test_check_sandbox_status_fails_when_runner_import_fails(forven_db, monkeypatch):
    from forven.diagnostics import FAIL, check_sandbox_status
    import sys

    monkeypatch.setattr(
        "forven.sandbox.strategy_adapter.get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    # Force import failure by deleting the module then breaking its parent
    # package's __getattr__. Simpler: monkeypatch sys.modules to a sentinel
    # that raises on attribute access.
    real = sys.modules.pop("forven.sandbox.subprocess_runner", None)

    class _BoomMod:
        def __getattr__(self, name):
            raise ImportError(f"simulated failure for {name}")

    sys.modules["forven.sandbox.subprocess_runner"] = _BoomMod()  # type: ignore[assignment]
    try:
        r = check_sandbox_status()
        assert r.status == FAIL
        assert "runner import" in r.summary
    finally:
        sys.modules.pop("forven.sandbox.subprocess_runner", None)
        if real is not None:
            sys.modules["forven.sandbox.subprocess_runner"] = real


def test_snapshot_includes_sandbox_status(forven_db, monkeypatch):
    """check_sandbox_status must be wired into run_all_checks."""
    monkeypatch.setattr(
        "forven.sandbox.strategy_adapter.get_sandbox_config",
        lambda: {"enabled": False, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    snap = snapshot()
    names = [c["name"] for c in snap["checks"]]
    assert "sandbox_status" in names
