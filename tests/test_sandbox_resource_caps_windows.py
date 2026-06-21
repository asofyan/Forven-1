"""Windows-only Job Object cap tests for the sandbox runner (P2-T06).

Skipped entirely on non-Windows platforms — the POSIX equivalents live in
``test_sandbox_resource_caps_posix.py`` (P2-T05).

Acceptance points:
- 32MB-cap strategy that allocates 128MB is killed by the Job Object;
  exit_code reflects the kill, memory_peak_mb roughly tracks the cap.
- wall_s=0.5 on `while True: pass` kills the entire job; timed_out=True.
- Job Object query returns non-None telemetry for clean runs.
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

if sys.platform != "win32":
    pytest.skip("Windows-only Job Object caps", allow_module_level=True)

from forven import db as forven_db  # noqa: E402
from forven.sandbox.subprocess_runner import (  # noqa: E402
    TIMEOUT_EXIT_CODE,
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
    """Allocating 128MB under a 32MB cap must end with exit_code != 0."""
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
    result = run_strategy_in_subprocess(
        strat, {}, timeout_s=10.0, mem_mb=32, cpu_s=10
    )
    assert result.exit_code != 0, (
        f"Job Object should have killed the child "
        f"(exit_code={result.exit_code}, stdout={result.stdout_payload}, "
        f"stderr={result.stderr_text!r})"
    )


def test_wall_clock_timeout_kills_busy_loop(fresh_db, tmp_path: Path):
    """`while True: pass` under wall=0.5s must trigger the timeout path."""
    strat = _write(
        tmp_path / "spin.py",
        "def generate_signal(ohlcv):\n    while True:\n        pass\n",
    )
    result = run_strategy_in_subprocess(
        strat, {}, timeout_s=0.5, mem_mb=128, cpu_s=30
    )
    assert result.timed_out is True
    assert result.exit_code == TIMEOUT_EXIT_CODE
    assert result.wall_seconds < 5.0


def test_clean_strategy_records_job_telemetry(fresh_db, tmp_path: Path):
    """Job-Object query path returns non-None telemetry for a clean run."""
    strat = _write(
        tmp_path / "noop.py",
        "def generate_signal(ohlcv):\n    return {'trades': [], 'stats': {}}\n",
    )
    result = run_strategy_in_subprocess(strat, {}, timeout_s=10.0)
    assert result.exit_code == 0
    # PeakJobMemoryUsed and TotalUserTime+TotalKernelTime should both populate.
    assert result.memory_peak_mb is not None
    assert result.cpu_seconds is not None
    assert result.cpu_seconds >= 0.0
