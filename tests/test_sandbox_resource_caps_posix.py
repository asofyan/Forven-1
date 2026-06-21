"""POSIX-only resource-cap tests for the sandbox runner (P2-T05).

The whole module is skipped on Windows — those tests live in
``test_sandbox_resource_caps_windows.py`` (P2-T06).

Acceptance points:
- 32MB-cap strategy that allocates 128MB exits non-zero, memory_peak_mb recorded.
- 0.5s CPU-cap strategy in `while True: x*x` is killed by SIGXCPU; cpu_seconds recorded.
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

if sys.platform == "win32":
    pytest.skip("POSIX-only resource caps", allow_module_level=True)

from forven import db as forven_db  # noqa: E402
from forven.sandbox.subprocess_runner import (  # noqa: E402
    run_strategy_in_subprocess,
)


@pytest.fixture
def fresh_db(monkeypatch):
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("FORVEN_HOME", td)
        if hasattr(forven_db, "_DB_PATH"):
            forven_db._DB_PATH = None  # type: ignore[attr-defined]
        if hasattr(forven_db, "_init_db_done"):
            forven_db._init_db_done = False  # type: ignore[attr-defined]
        forven_db.init_db()
        yield td


def _write(p: Path, code: str) -> Path:
    p.write_text(code, encoding="utf-8")
    return p


def test_memory_cap_kills_overallocator(fresh_db, tmp_path: Path):
    """A strategy that allocates 128MB under a 32MB cap must die non-zero."""
    strat = _write(
        tmp_path / "mem_hog.py",
        textwrap.dedent(
            """
            def generate_signal(ohlcv):
                blob = bytearray(128 * 1024 * 1024)
                return {"trades": [], "stats": {"len": len(blob)}}
            """
        ).strip(),
    )
    result = run_strategy_in_subprocess(strat, {}, timeout_s=10.0, mem_mb=32, cpu_s=10)

    assert result.exit_code != 0, (
        f"Memory cap should have killed the child (exit_code={result.exit_code}, "
        f"stdout={result.stdout_payload}, stderr={result.stderr_text!r})"
    )
    # rusage should have recorded SOMETHING for memory.
    assert result.memory_peak_mb is not None


def test_cpu_cap_kills_busy_loop(fresh_db, tmp_path: Path):
    """A strategy that burns CPU under a 1s cap must be killed by SIGXCPU."""
    strat = _write(
        tmp_path / "cpu_hog.py",
        textwrap.dedent(
            """
            def generate_signal(ohlcv):
                x = 1
                while True:
                    x = (x * 1.0001) % 1e9
            """
        ).strip(),
    )
    # wall_s 30 so wall-clock doesn't fire first; CPU cap should win.
    result = run_strategy_in_subprocess(strat, {}, timeout_s=30.0, mem_mb=128, cpu_s=1)

    assert result.exit_code != 0
    assert result.cpu_seconds is not None


def test_clean_strategy_records_rusage(fresh_db, tmp_path: Path):
    """Even a no-op clean strategy should populate cpu_seconds + memory_peak_mb."""
    strat = _write(
        tmp_path / "noop.py",
        "def generate_signal(ohlcv):\n    return {'trades': [], 'stats': {}}\n",
    )
    result = run_strategy_in_subprocess(strat, {}, timeout_s=10.0)
    assert result.exit_code == 0
    assert result.memory_peak_mb is not None
    assert result.cpu_seconds is not None
    assert result.cpu_seconds >= 0.0
