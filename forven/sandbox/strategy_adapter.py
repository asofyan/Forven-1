"""SandboxedStrategy adapter for AI-generated strategies (P2-T08).

Provides a class with the same ``.evaluate(ohlcv)`` interface that existing
strategy callers use, but forwards each call through
:func:`forven.sandbox.subprocess_runner.run_strategy_in_subprocess`. Allows
new load-sites to opt into sandbox isolation without changing callers.

Settings keys (in the flat dict returned by
:func:`forven.api_core.get_settings`):

- ``sandbox_enabled`` (default False) — master switch.
- ``sandbox_mem_mb`` (256) — Job Object / RLIMIT_AS cap.
- ``sandbox_cpu_s`` (30) — CPU time cap.
- ``sandbox_wall_s`` (60) — wall-clock kill timer.

Path-based gating: only strategies under ``juddex/strategies/custom/`` (or
the modern ``forven/strategies/custom/``) are eligible for the sandbox.
Built-in strategies stay in-process — they're trusted code shipped with
the app.

Fail-open symmetry with :mod:`forven.sandbox.shell_guard`: if the runner
itself fails to spawn (e.g., entrypoint module missing on a stripped
build), :func:`load_sandboxed` returns None and the caller is expected
to fall back to its existing in-process loader. Better to run
un-sandboxed than to refuse to load any strategy.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger("forven.sandbox.strategy_adapter")

# Path fragments that mark a strategy as "user-generated" → sandbox-eligible.
# Path comparison is normalized: forward slashes only, lowercase, no anchors.
_CUSTOM_PATH_FRAGMENTS: tuple[str, ...] = (
    "juddex/strategies/custom/",
    "forven/strategies/custom/",
)


def _normalize(p: Path | str) -> str:
    return str(p).replace("\\", "/").lower()


def is_custom_strategy_path(path: Path | str) -> bool:
    """Return True if *path* is under one of the custom-strategy roots.

    Built-in strategies (under ``builtin/``) return False so they bypass the
    sandbox — they're trusted code we ship.
    """
    norm = _normalize(path)
    return any(frag in norm for frag in _CUSTOM_PATH_FRAGMENTS)


def get_sandbox_config() -> dict[str, Any]:
    """Read sandbox-related keys from the persisted settings dict.

    Returns a dict with keys: ``enabled``, ``mem_mb``, ``cpu_s``, ``wall_s``.
    Falls back to safe defaults on any failure (settings missing, file
    corrupted, etc.) — never raises.
    """
    defaults = {
        "enabled": False,
        "mem_mb": 256,
        "cpu_s": 30,
        "wall_s": 60,
    }
    try:
        from forven.api_core import get_settings  # noqa: PLC0415

        s = get_settings()
        if not isinstance(s, dict):
            return defaults
        return {
            "enabled": bool(s.get("sandbox_enabled", False)),
            "mem_mb": int(s.get("sandbox_mem_mb", 256)),
            "cpu_s": int(s.get("sandbox_cpu_s", 30)),
            "wall_s": int(s.get("sandbox_wall_s", 60)),
        }
    except Exception as exc:  # noqa: BLE001
        log.debug("get_sandbox_config fallback (%s)", exc)
        return defaults


class SandboxedStrategy:
    """Adapter exposing ``.evaluate(ohlcv) -> dict`` over a subprocess call.

    Constructed directly via :func:`load_sandboxed` so callers don't have
    to know about path gating + settings.

    The subprocess returns a JSON ``{trades: [...], stats: {...}}`` payload
    — that dict is what ``.evaluate`` returns. On AST block / timeout /
    crash the dict has shape ``{"trades": [], "stats": {}, "error": "..."}``
    so callers don't need to handle exceptions.
    """

    def __init__(
        self,
        strategy_path: Path,
        *,
        strategy_id: str | None = None,
        mem_mb: int = 256,
        cpu_s: int = 30,
        wall_s: int = 60,
    ) -> None:
        self.strategy_path = Path(strategy_path)
        self.strategy_id = strategy_id
        self.mem_mb = mem_mb
        self.cpu_s = cpu_s
        self.wall_s = wall_s

    def evaluate(self, ohlcv: dict[str, Any] | None = None) -> dict[str, Any]:
        from forven.sandbox.subprocess_runner import (  # noqa: PLC0415
            run_strategy_in_subprocess,
        )

        result = run_strategy_in_subprocess(
            self.strategy_path,
            ohlcv or {},
            timeout_s=float(self.wall_s),
            mem_mb=self.mem_mb,
            cpu_s=self.cpu_s,
            strategy_id=self.strategy_id,
        )

        if result.stdout_payload is not None:
            return result.stdout_payload

        # Map non-payload outcomes to a uniform error-shaped dict so callers
        # never see None.
        if result.security_events:
            evt = result.security_events[0]
            err = f"sandbox_block:{evt.get('type', 'unknown')}"
        elif result.timed_out:
            err = "sandbox_timeout"
        else:
            err = f"sandbox_exit_{result.exit_code}"
        return {"trades": [], "stats": {}, "error": err}


def load_sandboxed(
    path: Path | str,
    *,
    strategy_id: str | None = None,
) -> SandboxedStrategy | None:
    """Return a SandboxedStrategy adapter, or None if not eligible.

    The caller is expected to fall back to its in-process loader on None.
    Returns None when:

    * ``sandbox_enabled`` is False (operator hasn't opted in)
    * The path isn't under a custom-strategy root (built-ins bypass sandbox)
    * The path doesn't exist (caller will get a clearer error from its
      own loader)

    Note: this DOES NOT pre-flight the AST guard. The runner does that on
    every ``.evaluate()`` call. Callers wanting an upfront block check
    should call :func:`forven.sandbox.ast_guard.scan_file` directly.
    """
    cfg = get_sandbox_config()
    if not cfg["enabled"]:
        return None

    p = Path(path)
    if not p.exists():
        return None

    if not is_custom_strategy_path(p):
        return None

    return SandboxedStrategy(
        p,
        strategy_id=strategy_id,
        mem_mb=cfg["mem_mb"],
        cpu_s=cfg["cpu_s"],
        wall_s=cfg["wall_s"],
    )
