"""Tests for forven.sandbox.subprocess_runner (P2-T04).

Acceptance points covered:
- hello-world strategy returns valid stdout payload
- AST-blocked strategy never spawns a child
- child crash captured in exit_code without raising
- timeout=0.5s on `while True: pass` results in timed_out + exit 124
- child env doesn't see ANTHROPIC_API_KEY
- sandbox_runs has a row for every invocation, including AST-blocked ones
"""
from __future__ import annotations

import os
import tempfile
import textwrap
from pathlib import Path

import pytest

from forven import db as forven_db
from forven.sandbox.subprocess_runner import (
    SubprocessResult,
    TIMEOUT_EXIT_CODE,
    _build_child_env,
    run_strategy_in_subprocess,
)


# ---------- helpers --------------------------------------------------------

HELLO_STRATEGY = textwrap.dedent(
    """
    def generate_signal(ohlcv):
        return {"trades": [{"action": "buy", "size": 1}], "stats": {"hello": "world"}}
    """
).strip()

INFINITE_LOOP_STRATEGY = textwrap.dedent(
    """
    def generate_signal(ohlcv):
        while True:
            pass
    """
).strip()

CRASH_STRATEGY = textwrap.dedent(
    """
    def generate_signal(ohlcv):
        raise RuntimeError("boom")
    """
).strip()

AST_BLOCKED_STRATEGY = textwrap.dedent(
    """
    import os
    import subprocess

    def generate_signal(ohlcv):
        return {"trades": [], "stats": {}}
    """
).strip()


@pytest.fixture
def fresh_db(monkeypatch):
    """Re-route FORVEN_HOME so sandbox_runs writes go to a tmpdir DB."""
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("FORVEN_HOME", td)
        if hasattr(forven_db, "_DB_PATH"):
            forven_db._DB_PATH = None  # type: ignore[attr-defined]
        if hasattr(forven_db, "_init_db_done"):
            forven_db._init_db_done = False  # type: ignore[attr-defined]
        forven_db.init_db()
        yield td


def _write_strategy(tmp_path: Path, code: str, name: str = "strat.py") -> Path:
    p = tmp_path / name
    p.write_text(code, encoding="utf-8")
    return p


def _sandbox_runs(conn) -> list[dict]:
    return [dict(r) for r in conn.execute("SELECT * FROM sandbox_runs ORDER BY id")]


# ---------- tests ----------------------------------------------------------


def test_hello_world_strategy_returns_payload(fresh_db, tmp_path: Path):
    strat = _write_strategy(tmp_path, HELLO_STRATEGY)
    result = run_strategy_in_subprocess(strat, {"bars": []}, timeout_s=15.0)

    assert isinstance(result, SubprocessResult)
    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stdout_payload is not None
    assert result.stdout_payload.get("stats", {}).get("hello") == "world"
    assert result.wall_seconds >= 0.0


def test_hello_world_persists_run_row(fresh_db, tmp_path: Path):
    strat = _write_strategy(tmp_path, HELLO_STRATEGY)
    run_strategy_in_subprocess(strat, {}, timeout_s=15.0)

    with forven_db.get_db() as conn:
        rows = _sandbox_runs(conn)

    assert len(rows) == 1
    assert rows[0]["kind"] == "run"
    assert rows[0]["exit_code"] == 0
    assert rows[0]["timed_out"] == 0


def test_ast_blocked_strategy_never_spawns(fresh_db, tmp_path: Path):
    strat = _write_strategy(tmp_path, AST_BLOCKED_STRATEGY)
    result = run_strategy_in_subprocess(strat, {}, timeout_s=15.0)

    assert result.exit_code == -1
    assert result.timed_out is False
    assert result.stdout_payload is None
    assert any(ev.get("type") == "ast_block" for ev in result.security_events)
    findings = result.security_events[0]["findings"]
    assert any(f["kind"] == "forbidden_import" for f in findings)


def test_ast_blocked_persists_scan_row(fresh_db, tmp_path: Path):
    strat = _write_strategy(tmp_path, AST_BLOCKED_STRATEGY)
    run_strategy_in_subprocess(strat, {}, timeout_s=15.0)

    with forven_db.get_db() as conn:
        rows = _sandbox_runs(conn)

    assert len(rows) == 1
    assert rows[0]["kind"] == "scan"
    assert rows[0]["exit_code"] == -1
    assert rows[0]["error"] == "ast_block"
    assert rows[0]["ast_findings_json"]


def test_missing_strategy_handled_gracefully(fresh_db, tmp_path: Path):
    result = run_strategy_in_subprocess(tmp_path / "does_not_exist.py", {}, timeout_s=5.0)
    assert result.exit_code == -1
    assert any(ev.get("type") == "ast_block" for ev in result.security_events)


def test_crash_does_not_raise_in_runner(fresh_db, tmp_path: Path):
    """A strategy that raises must produce a non-zero exit_code, not crash the runner."""
    strat = _write_strategy(tmp_path, CRASH_STRATEGY)
    result = run_strategy_in_subprocess(strat, {}, timeout_s=15.0)

    assert isinstance(result, SubprocessResult)
    assert result.exit_code != 0
    assert result.timed_out is False
    # Stderr should mention the traceback OR stdout payload should carry the error
    has_signal = "RuntimeError" in (result.stderr_text or "") or (
        result.stdout_payload is not None
        and "boom" in str(result.stdout_payload.get("error", ""))
    )
    assert has_signal


def test_timeout_kills_infinite_loop(fresh_db, tmp_path: Path):
    strat = _write_strategy(tmp_path, INFINITE_LOOP_STRATEGY)
    result = run_strategy_in_subprocess(strat, {}, timeout_s=0.5)

    assert result.timed_out is True
    assert result.exit_code == TIMEOUT_EXIT_CODE
    # 0.5s timeout + a bit of slack for kill cleanup
    assert result.wall_seconds < 5.0


def test_timeout_persists_with_timed_out_flag(fresh_db, tmp_path: Path):
    strat = _write_strategy(tmp_path, INFINITE_LOOP_STRATEGY)
    run_strategy_in_subprocess(strat, {}, timeout_s=0.5)

    with forven_db.get_db() as conn:
        rows = _sandbox_runs(conn)

    assert len(rows) == 1
    assert rows[0]["kind"] == "run"
    assert rows[0]["timed_out"] == 1
    assert rows[0]["exit_code"] == TIMEOUT_EXIT_CODE


def test_child_env_does_not_leak_secrets(monkeypatch):
    """The whitelist env builder must NOT pass secrets to the child.

    A user strategy can't `import os` (AST guard blocks it) so we test the
    env builder directly. End-to-end behavior is tested by the fact that
    Popen passes exactly this dict to the child via env=.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-fake-test-secret")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-fake-or-secret")
    monkeypatch.setenv("FORVEN_HOME", "C:/should-not-leak")
    monkeypatch.setenv("FORVEN_DEBUG", "1")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "leaky")

    env = _build_child_env()

    forbidden = [
        "ANTHROPIC_API_KEY",
        "OPENROUTER_API_KEY",
        "FORVEN_HOME",
        "FORVEN_DEBUG",
        "AWS_SECRET_ACCESS_KEY",
    ]
    for key in forbidden:
        assert key not in env, f"Secret '{key}' leaked to child env: {env.get(key)!r}"

    # Useful keys that ARE allowed:
    if os.environ.get("PATH"):
        assert "PATH" in env


def test_strategy_id_recorded_in_row(fresh_db, tmp_path: Path):
    strat = _write_strategy(tmp_path, HELLO_STRATEGY)
    run_strategy_in_subprocess(
        strat, {}, timeout_s=15.0, strategy_id="S99999"
    )
    with forven_db.get_db() as conn:
        rows = _sandbox_runs(conn)
    assert rows[0]["strategy_id"] == "S99999"


def test_clean_strategy_without_generate_signal_returns_loaded(fresh_db, tmp_path: Path):
    """Permissive: a clean module without generate_signal still completes."""
    strat = _write_strategy(tmp_path, "x = 1\ny = 2\n")
    result = run_strategy_in_subprocess(strat, {}, timeout_s=15.0)
    assert result.exit_code == 0
    assert result.stdout_payload is not None
    assert result.stdout_payload.get("stats", {}).get("loaded") is True


def test_runner_returns_subprocess_result_dataclass(fresh_db, tmp_path: Path):
    strat = _write_strategy(tmp_path, HELLO_STRATEGY)
    result = run_strategy_in_subprocess(strat, {}, timeout_s=15.0)
    # Ensure all documented fields are present
    for attr in (
        "exit_code",
        "timed_out",
        "memory_peak_mb",
        "cpu_seconds",
        "wall_seconds",
        "stdout_payload",
        "stderr_text",
        "security_events",
    ):
        assert hasattr(result, attr)
