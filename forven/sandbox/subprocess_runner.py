"""Subprocess sandbox runner for AI-generated strategies (P2-T04).

Wraps :mod:`forven.sandbox.ast_guard` (pre-flight) and
:mod:`forven.sandbox._child_entrypoint` (the spawned script) into a single
``run_strategy_in_subprocess(...)`` call. Persists every invocation to the
``sandbox_runs`` table — including AST-blocked runs that never spawned a
child — so the operator has end-to-end audit history.

T05 (POSIX) and T06 (Windows Job Objects) layer in resource caps + true
cross-OS wall-clock kill on top of this runner. T04 ships with simple
``proc.kill()`` on timeout, which is enough for unit tests.

Environment: builds an explicit whitelist of env vars to pass to the child
(PATH + SYSTEMROOT on Windows, PATH + HOME on POSIX, plus TEMP/TMP). Never
inherits ``ANTHROPIC_API_KEY``, ``OPENROUTER_API_KEY``, ``FORVEN_*``,
``FORVEN_*``, etc. — secrets stay in the parent.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from forven.sandbox import _BLAS_THREAD_ENV
from forven.sandbox.ast_guard import scan_file

if sys.platform == "win32":
    from forven.sandbox import _jobobject_windows as _jow
else:
    _jow = None  # type: ignore[assignment]

log = logging.getLogger("forven.sandbox.subprocess_runner")

# Wall-clock kill exit code. POSIX timeout(1) uses 124; we adopt the
# convention so operators can grep for it across logs.
TIMEOUT_EXIT_CODE: int = 124

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_CHILD_ENTRYPOINT = Path(__file__).resolve().parent / "_child_entrypoint.py"


@dataclass
class SubprocessResult:
    exit_code: int
    timed_out: bool
    memory_peak_mb: int | None
    cpu_seconds: float | None
    wall_seconds: float
    stdout_payload: dict | None
    stderr_text: str
    security_events: list[dict] = field(default_factory=list)


def _build_child_env() -> dict[str, str]:
    """Whitelist-only env. Never blacklist — too easy to miss new secrets."""
    src = os.environ
    keep_keys: list[str] = ["PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR"]
    if sys.platform != "win32":
        keep_keys.extend(["HOME", "LANG", "LC_ALL"])

    env: dict[str, str] = {}
    for k in keep_keys:
        v = src.get(k)
        if v is not None:
            env[k] = v

    # Cap BLAS threads (matches Phase 0 run_code() conventions).
    for k, v in _BLAS_THREAD_ENV.items():
        env.setdefault(k, v)
    return env


def _persist_scan_only_row(
    *,
    strategy_id: str | None,
    started_at: str,
    ended_at: str,
    ast_findings: list[dict],
    error: str | None,
) -> int | None:
    """Insert a `kind='scan'` row when AST blocks the strategy pre-spawn."""
    try:
        from forven.db import get_db

        with get_db() as conn:
            cur = conn.execute(
                """INSERT INTO sandbox_runs
                (strategy_id, kind, started_at, ended_at, exit_code,
                 timed_out, ast_findings_json, error)
                VALUES (?, 'scan', ?, ?, -1, 0, ?, ?)""",
                (
                    strategy_id,
                    started_at,
                    ended_at,
                    json.dumps(ast_findings),
                    error,
                ),
            )
            return int(cur.lastrowid) if cur.lastrowid else None
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to persist scan-only sandbox_runs row: %s", exc)
        return None


def _persist_run_row(
    *,
    strategy_id: str | None,
    started_at: str,
    ended_at: str,
    result: SubprocessResult,
) -> int | None:
    try:
        from forven.db import get_db

        with get_db() as conn:
            cur = conn.execute(
                """INSERT INTO sandbox_runs
                (strategy_id, kind, started_at, ended_at, exit_code,
                 memory_peak_mb, cpu_seconds, wall_seconds,
                 timed_out, security_events_json, error)
                VALUES (?, 'run', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    strategy_id,
                    started_at,
                    ended_at,
                    result.exit_code,
                    result.memory_peak_mb,
                    result.cpu_seconds,
                    result.wall_seconds,
                    1 if result.timed_out else 0,
                    json.dumps(result.security_events) if result.security_events else None,
                    None,
                ),
            )
            return int(cur.lastrowid) if cur.lastrowid else None
    except Exception as exc:  # noqa: BLE001
        log.warning("Failed to persist run sandbox_runs row: %s", exc)
        return None


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def _build_posix_preexec(mem_mb: int, cpu_s: int):
    """POSIX-only: return a preexec_fn that applies rlimit caps + setpgrp.

    Called in the child after fork() but before exec(). `setpgrp()` puts the
    child in its own process group so the runner can `os.killpg` the entire
    tree on timeout — prevents grandchildren from outliving the leader.
    """
    if sys.platform == "win32":
        return None
    import resource  # noqa: PLC0415 — POSIX only

    def _apply() -> None:
        os.setpgrp()
        # RLIMIT_AS = virtual memory, in bytes.
        mem_bytes = mem_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
        # RLIMIT_CPU = CPU seconds; soft hits SIGXCPU, hard hits SIGKILL.
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))

    return _apply


def _read_rusage_for_children() -> tuple[int | None, float | None]:
    """POSIX-only: read RUSAGE_CHILDREN. Returns (memory_peak_mb, cpu_seconds).

    `ru_maxrss` is in KB on Linux, bytes on macOS — normalize to MB.
    """
    if sys.platform == "win32":
        return None, None
    try:
        import resource  # noqa: PLC0415

        ru = resource.getrusage(resource.RUSAGE_CHILDREN)
        if sys.platform == "darwin":
            mem_mb = ru.ru_maxrss // (1024 * 1024)  # bytes → MB
        else:
            mem_mb = ru.ru_maxrss // 1024  # KB → MB
        cpu_s = float(ru.ru_utime + ru.ru_stime)
        return int(mem_mb), cpu_s
    except Exception:  # noqa: BLE001
        return None, None


def _kill_proc_tree(proc: subprocess.Popen, job=None) -> None:
    """Kill the child and the entire tree it leads.

    POSIX: `os.killpg` on the process group set by `setpgrp()` in the child.
    Windows: `TerminateJobObject` on the Job — kills leader + grandchildren
    in one syscall. Falls back to `proc.kill()` if no Job is attached or
    Win32 termination fails.
    """
    if sys.platform != "win32":
        try:
            import signal  # noqa: PLC0415

            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return
        except (ProcessLookupError, PermissionError, OSError):
            pass
    elif job is not None and _jow is not None:
        if _jow.terminate_job(job, exit_code=TIMEOUT_EXIT_CODE):
            return
    try:
        proc.kill()
    except Exception:  # noqa: BLE001
        pass


def run_strategy_in_subprocess(
    strategy_path: Path | str,
    ohlcv_payload: dict[str, Any] | None = None,
    *,
    timeout_s: float = 60.0,
    mem_mb: int = 256,
    cpu_s: int = 30,
    strategy_id: str | None = None,
) -> SubprocessResult:
    """Run *strategy_path* in an isolated subprocess.

    Pre-flight: AST guard. If `ok=False`, returns a SubprocessResult with
    `exit_code=-1` and a single `ast_block` security event WITHOUT spawning
    a child. The scan is still recorded as a `kind='scan'` row.

    On spawn: writes the OHLCV payload to stdin, waits up to *timeout_s*,
    reads stdout/stderr, parses stdout as JSON. On timeout: kills the
    process group (POSIX) or process (Windows; T06 will replace this with
    Job Object termination), sets `timed_out=True`, `exit_code=124`.

    Never raises: a child segfault becomes `exit_code=<negative signal>`,
    a non-JSON stdout becomes `stdout_payload=None`, a missing strategy
    becomes an AST `syntax_error`/`file_too_large` finding via scan_file.
    """
    sp = Path(strategy_path)
    started_at = _now_iso()

    # ---- Pre-flight: AST guard ------------------------------------------------
    if not sp.exists():
        # Synthesize a finding so callers see a normal AstReport-shaped event.
        ast_findings = [
            {
                "kind": "missing_file",
                "lineno": 0,
                "col": 0,
                "message": f"Strategy file not found: {sp}",
                "node_repr": "",
            }
        ]
        ended_at = _now_iso()
        _persist_scan_only_row(
            strategy_id=strategy_id,
            started_at=started_at,
            ended_at=ended_at,
            ast_findings=ast_findings,
            error="missing_file",
        )
        return SubprocessResult(
            exit_code=-1,
            timed_out=False,
            memory_peak_mb=None,
            cpu_seconds=None,
            wall_seconds=0.0,
            stdout_payload=None,
            stderr_text=f"Strategy file not found: {sp}",
            security_events=[{"type": "ast_block", "findings": ast_findings}],
        )

    report = scan_file(sp)
    if not report.ok:
        ast_findings = [asdict(f) for f in report.findings]
        ended_at = _now_iso()
        _persist_scan_only_row(
            strategy_id=strategy_id,
            started_at=started_at,
            ended_at=ended_at,
            ast_findings=ast_findings,
            error="ast_block",
        )
        return SubprocessResult(
            exit_code=-1,
            timed_out=False,
            memory_peak_mb=None,
            cpu_seconds=None,
            wall_seconds=0.0,
            stdout_payload=None,
            stderr_text=f"AST guard blocked spawn: {len(report.findings)} finding(s)",
            security_events=[{"type": "ast_block", "findings": ast_findings}],
        )

    # ---- Spawn ----------------------------------------------------------------
    cmd = [
        sys.executable,
        "-B",  # don't write .pyc
        "-I",  # isolated mode: no PYTHONPATH, no user site
        str(_CHILD_ENTRYPOINT),
        str(sp),
    ]
    env = _build_child_env()
    stdin_blob = json.dumps({"ohlcv": ohlcv_payload or {}})

    wall_start = time.monotonic()
    popen_kwargs: dict[str, Any] = dict(
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(_REPO_ROOT),
        env=env,
        text=True,
        encoding="utf-8",
    )
    job = None
    if sys.platform == "win32" and _jow is not None:
        # Win32: create the Job, then assign the child immediately after spawn.
        # Spawning CREATE_SUSPENDED would close the assign-then-run race, but
        # subprocess.Popen on Windows doesn't expose the main thread handle —
        # resuming the child requires reaching into Popen internals or
        # NtResumeProcess. The microseconds between spawn and assign aren't
        # enough for hostile code to allocate past a sane cap, so we accept
        # the small race.
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        job = _jow.create_job_with_limits(mem_mb=mem_mb, cpu_s=cpu_s)
    else:
        # POSIX-only: apply rlimit caps + setpgrp in the child.
        popen_kwargs["preexec_fn"] = _build_posix_preexec(mem_mb, cpu_s)

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except Exception as exc:  # noqa: BLE001
        if job is not None and _jow is not None:
            _jow.close_job(job)
        wall_elapsed = time.monotonic() - wall_start
        ended_at = _now_iso()
        result = SubprocessResult(
            exit_code=-1,
            timed_out=False,
            memory_peak_mb=None,
            cpu_seconds=None,
            wall_seconds=wall_elapsed,
            stdout_payload=None,
            stderr_text=f"spawn_failed: {exc}",
        )
        _persist_run_row(
            strategy_id=strategy_id,
            started_at=started_at,
            ended_at=ended_at,
            result=result,
        )
        return result

    # Windows: assign the freshly-spawned child to the Job Object.
    if sys.platform == "win32" and job is not None and _jow is not None:
        if not _jow.assign_pid_to_job(job, proc.pid):
            log.warning("Failed to assign sandbox pid %s to Job; running without limits", proc.pid)

    timed_out = False
    try:
        stdout_text, stderr_text = proc.communicate(input=stdin_blob, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_proc_tree(proc, job=job)
        try:
            stdout_text, stderr_text = proc.communicate(timeout=2)
        except Exception:  # noqa: BLE001
            stdout_text, stderr_text = "", "timeout cleanup failed"

    wall_elapsed = time.monotonic() - wall_start
    exit_code = TIMEOUT_EXIT_CODE if timed_out else (proc.returncode if proc.returncode is not None else -1)

    if sys.platform == "win32" and job is not None and _jow is not None:
        mem_peak_mb, cpu_seconds = _jow.query_job_telemetry(job)
        _jow.close_job(job)
    else:
        mem_peak_mb, cpu_seconds = _read_rusage_for_children()

    stdout_payload: dict | None = None
    if stdout_text:
        try:
            parsed = json.loads(stdout_text.strip())
            if isinstance(parsed, dict):
                stdout_payload = parsed
        except json.JSONDecodeError:
            stdout_payload = None

    ended_at = _now_iso()
    result = SubprocessResult(
        exit_code=exit_code,
        timed_out=timed_out,
        memory_peak_mb=mem_peak_mb,
        cpu_seconds=cpu_seconds,
        wall_seconds=wall_elapsed,
        stdout_payload=stdout_payload,
        stderr_text=(stderr_text or "")[:5000],
        security_events=[],
    )

    _persist_run_row(
        strategy_id=strategy_id,
        started_at=started_at,
        ended_at=ended_at,
        result=result,
    )
    return result
