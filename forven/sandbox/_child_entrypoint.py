"""Subprocess child entrypoint for sandboxed strategy execution (P2-T04).

Spawned by :mod:`forven.sandbox.subprocess_runner` as::

    python -B -I _child_entrypoint.py <strategy_path>

`-I` strips PYTHONPATH and user site, `-B` skips bytecode writes. The parent
restricts the child env to PATH/SYSTEMROOT/TEMP only, so secrets like
ANTHROPIC_API_KEY never leak in.

Protocol:
- Reads ``{"ohlcv": ...}`` JSON from stdin (one line, single object).
- Resolves the strategy at ``argv[1]`` via ``importlib.util.spec_from_file_location``.
- Calls ``generate_signal(ohlcv)`` if defined; otherwise returns an empty
  ``{"trades": [], "stats": {}}`` payload (so the hello-world fixture and
  malformed strategies both produce a parseable result).
- Writes ``{"trades": [...], "stats": {...}}`` JSON to stdout, exits 0.
- On any exception, writes ``{"error": "<msg>", "trades": [], "stats": {}}``
  and exits 1. Never re-raises — the parent inspects exit_code + stderr.

Runtime hardening:
- Installs a ``sys.meta_path`` finder that blocks any import not in
  ``ALLOWED_CHILD_MODULES``. This catches both ``import os`` and
  ``__import__('os')`` because both flow through the import system.
- Note: we do NOT mutate the global ``builtins`` module — Python's importlib
  internally calls ``__import__`` during ``exec_module`` and stripping it
  would brick the loader. The AST guard (P2-T02) catches static
  ``eval``/``exec``/``compile``/``__import__`` calls in user source. Phase
  2 follow-up tasks (T05/T06) layer in per-process resource caps.
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import importlib.util
import json
import sys
import traceback
from pathlib import Path

# `-I` strips PYTHONPATH so we have to teach sys.path where forven lives.
# This file sits at <REPO_ROOT>/forven/sandbox/_child_entrypoint.py.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from forven.sandbox.allowed_modules import is_module_allowed  # noqa: E402


class _AllowlistFinder(importlib.abc.MetaPathFinder):
    """sys.meta_path entry that rejects any non-allowlisted import.

    Sits BEFORE the default finders so it gets first refusal. Returning
    None lets the next finder try; raising ImportError aborts the import.
    """

    def find_spec(
        self,
        fullname: str,
        path,  # noqa: ARG002
        target=None,  # noqa: ARG002
    ) -> importlib.machinery.ModuleSpec | None:
        if is_module_allowed(fullname):
            return None  # let default finders handle it
        # Allow re-imports of the entrypoint itself + already-imported modules
        # (sys.modules cache short-circuits this hook anyway, but be explicit).
        if fullname in sys.modules:
            return None
        raise ImportError(
            f"Sandbox: module '{fullname}' is not in the allowlist"
        )


def _load_strategy_module(path: Path):
    """Load the strategy via importlib.util — no need to expose its dir on
    sys.path, which would let the strategy import its sibling files."""
    spec = importlib.util.spec_from_file_location("_sandboxed_strategy", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec for {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    if len(sys.argv) < 2:
        sys.stdout.write(json.dumps({"error": "missing strategy path", "trades": [], "stats": {}}))
        sys.stdout.flush()
        return 2

    strategy_path = Path(sys.argv[1])

    # Read the OHLCV payload before installing the import gate so the JSON
    # parser can use whatever stdlib it needs without being intercepted.
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        sys.stdout.write(
            json.dumps({"error": f"bad stdin json: {exc}", "trades": [], "stats": {}})
        )
        sys.stdout.flush()
        return 3

    ohlcv = payload.get("ohlcv", {})

    # Install the import gate AFTER stdin parse but BEFORE strategy import.
    sys.meta_path.insert(0, _AllowlistFinder())

    try:
        module = _load_strategy_module(strategy_path)
    except ImportError as exc:
        sys.stderr.write(f"Sandbox import blocked: {exc}\n")
        sys.stdout.write(
            json.dumps({"error": str(exc), "trades": [], "stats": {}})
        )
        sys.stdout.flush()
        return 4
    except Exception as exc:  # noqa: BLE001 — child must never re-raise
        sys.stderr.write("Strategy load failed:\n" + traceback.format_exc())
        sys.stdout.write(
            json.dumps({"error": f"load failed: {exc}", "trades": [], "stats": {}})
        )
        sys.stdout.flush()
        return 5

    generate = getattr(module, "generate_signal", None)
    if not callable(generate):
        # Permissive: hello-world fixtures don't need to define generate_signal.
        sys.stdout.write(json.dumps({"trades": [], "stats": {"loaded": True}}))
        sys.stdout.flush()
        return 0

    try:
        result = generate(ohlcv)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("Strategy execution failed:\n" + traceback.format_exc())
        sys.stdout.write(
            json.dumps({"error": f"exec failed: {exc}", "trades": [], "stats": {}})
        )
        sys.stdout.flush()
        return 6

    if not isinstance(result, dict):
        result = {"trades": [], "stats": {"raw": str(result)[:500]}}
    result.setdefault("trades", [])
    result.setdefault("stats", {})

    sys.stdout.write(json.dumps(result, default=str))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
