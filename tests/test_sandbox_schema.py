"""Phase 2 schema migration tests — sandbox_runs (P2-T01).

Asserts the v25 DDL applies cleanly on a fresh DB and is a no-op on a
re-run, that the kind CHECK constraint holds, and that the three indexes
are created.
"""
from __future__ import annotations

import sqlite3
import tempfile

import pytest

from forven import db as forven_db


@pytest.fixture
def fresh_db(monkeypatch):
    """Build a one-off DB by routing FORVEN_HOME at a tmpdir."""
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("FORVEN_HOME", td)
        if hasattr(forven_db, "_DB_PATH"):
            forven_db._DB_PATH = None  # type: ignore[attr-defined]
        if hasattr(forven_db, "_init_db_done"):
            forven_db._init_db_done = False  # type: ignore[attr-defined]
        forven_db.init_db()
        with forven_db.get_db() as conn:
            yield conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type IN ('table','view') AND name=?",
        (name,),
    ).fetchone()
    return row is not None


def test_sandbox_runs_table_present(fresh_db):
    assert _table_exists(fresh_db, "sandbox_runs")


def test_sandbox_runs_columns(fresh_db):
    cols = {row["name"] for row in fresh_db.execute("PRAGMA table_info(sandbox_runs)")}
    expected = {
        "id",
        "strategy_id",
        "kind",
        "child_pid",
        "started_at",
        "ended_at",
        "exit_code",
        "memory_peak_mb",
        "cpu_seconds",
        "wall_seconds",
        "timed_out",
        "ast_findings_json",
        "security_events_json",
        "error",
        "created_at",
    }
    assert expected <= cols


def test_sandbox_runs_kind_check_constraint(fresh_db):
    """`kind` must be one of 'scan' or 'run' — anything else trips CHECK."""
    with pytest.raises(sqlite3.IntegrityError):
        fresh_db.execute(
            "INSERT INTO sandbox_runs (kind, started_at) VALUES (?, ?)",
            ("illegal", "2026-04-25T00:00:00+00:00"),
        )


def test_sandbox_runs_accepts_scan_kind(fresh_db):
    fresh_db.execute(
        "INSERT INTO sandbox_runs (kind, started_at) VALUES (?, ?)",
        ("scan", "2026-04-25T00:00:00+00:00"),
    )
    fresh_db.commit()
    row = fresh_db.execute("SELECT kind FROM sandbox_runs").fetchone()
    assert row["kind"] == "scan"


def test_sandbox_runs_accepts_run_kind(fresh_db):
    fresh_db.execute(
        "INSERT INTO sandbox_runs (kind, started_at) VALUES (?, ?)",
        ("run", "2026-04-25T00:00:00+00:00"),
    )
    fresh_db.commit()
    row = fresh_db.execute("SELECT kind FROM sandbox_runs").fetchone()
    assert row["kind"] == "run"


def test_sandbox_runs_started_at_required(fresh_db):
    with pytest.raises(sqlite3.IntegrityError):
        fresh_db.execute("INSERT INTO sandbox_runs (kind) VALUES ('scan')")


def test_sandbox_runs_timed_out_defaults_zero(fresh_db):
    fresh_db.execute(
        "INSERT INTO sandbox_runs (kind, started_at) VALUES (?, ?)",
        ("scan", "2026-04-25T00:00:00+00:00"),
    )
    fresh_db.commit()
    row = fresh_db.execute("SELECT timed_out FROM sandbox_runs").fetchone()
    assert row["timed_out"] == 0


def test_sandbox_runs_indices_present(fresh_db):
    indices = {
        row["name"]
        for row in fresh_db.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='sandbox_runs'"
        )
    }
    assert "idx_sandbox_runs_strategy" in indices
    assert "idx_sandbox_runs_kind" in indices
    assert "idx_sandbox_runs_timed_out" in indices


def test_sandbox_runs_strategy_id_nullable(fresh_db):
    """Ad-hoc /sandbox/scan rows have no strategy_id."""
    fresh_db.execute(
        "INSERT INTO sandbox_runs (kind, started_at) VALUES (?, ?)",
        ("scan", "2026-04-25T00:00:00+00:00"),
    )
    fresh_db.commit()
    row = fresh_db.execute("SELECT strategy_id FROM sandbox_runs").fetchone()
    assert row["strategy_id"] is None


def test_sandbox_runs_created_at_default_set(fresh_db):
    fresh_db.execute(
        "INSERT INTO sandbox_runs (kind, started_at) VALUES (?, ?)",
        ("scan", "2026-04-25T00:00:00+00:00"),
    )
    fresh_db.commit()
    row = fresh_db.execute("SELECT created_at FROM sandbox_runs").fetchone()
    assert row["created_at"]  # non-empty
    assert "T" in row["created_at"]  # ISO-8601 shape


def test_schema_version_is_at_least_25(fresh_db):
    row = fresh_db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    assert row["v"] >= 25


def test_migration_idempotent(fresh_db):
    """Re-running init_db on an already-migrated DB must not raise."""
    if hasattr(forven_db, "_init_db_done"):
        forven_db._init_db_done = False  # type: ignore[attr-defined]
    forven_db.init_db()
    row = fresh_db.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()
    assert row["v"] >= 25
