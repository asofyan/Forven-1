"""Regression tests for H-S4 (Windows sandbox Job Object resource limits)."""

from __future__ import annotations

import sys
import pytest

from forven import sandbox


pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="H-S4 Job Object plumbing only exercises on Windows",
)


def test_create_windows_job_object_returns_handle_or_none():
    job, kernel32 = sandbox._create_windows_job_object(max_memory_mb=128)
    try:
        # Either we got a real handle (job is non-zero int) and kernel32 is set,
        # or both are None — never one without the other.
        assert (job is None) == (kernel32 is None)
        if job is not None:
            assert kernel32 is not None
    finally:
        sandbox._close_job(job, kernel32)


def test_run_code_completes_under_job_object_limits():
    """Smoke test: simple code runs to completion via the Job Object path."""
    result = sandbox.run_code("print('ok')", timeout=10, max_memory_mb=128)
    assert result["returncode"] == 0
    assert "ok" in result["stdout"]
    assert result["timed_out"] is False


def test_run_code_kills_runaway_loop():
    """Tight infinite loop: must time out within the configured timeout."""
    code = "while True: pass"
    result = sandbox.run_code(code, timeout=2, max_memory_mb=128)
    assert result["timed_out"] is True
    assert result["returncode"] == -1
