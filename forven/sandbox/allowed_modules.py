"""Allowed-module whitelist + safe builtins for the sandbox subprocess child.

Used by the subprocess entrypoint (P2-T04) to gate `import` at runtime and
to strip dangerous builtins from the child's globals before any user code
runs. Pre-flight AST analysis (P2-T02 :mod:`forven.sandbox.ast_guard`)
catches static violations; this module is the runtime fallback for the
subset that AST can't see (e.g. importlib hops via approved-name aliases).
"""
from __future__ import annotations

import builtins

# Modules the subprocess child may import. `forven.market_data_view` is the
# read-only OHLCV API surface; nothing else under `forven.*` is allowed.
ALLOWED_CHILD_MODULES: frozenset[str] = frozenset(
    {
        "math",
        "statistics",
        "datetime",
        "json",
        "decimal",
        "numpy",
        "pandas",
        "forven.market_data_view",
    }
)

# Builtins removed from the child's globals before user code runs. AST guard
# blocks string-form `eval`/`exec`/`compile` already; stripping them at
# runtime defends against attribute-access laundering
# (`getattr(__builtins__, 'eval')`).
BLOCKED_BUILTINS: frozenset[str] = frozenset(
    {
        "open",
        "__import__",
        "exec",
        "eval",
        "compile",
        "input",
        "breakpoint",
        "help",
        "vars",
        "globals",
    }
)


def is_module_allowed(name: str) -> bool:
    """Return True if *name* (or a submodule of an allowed root) is whitelisted.

    >>> is_module_allowed("numpy")
    True
    >>> is_module_allowed("numpy.random")
    True
    >>> is_module_allowed("os")
    False
    """
    if not name:
        return False
    if name in ALLOWED_CHILD_MODULES:
        return True
    for allowed in ALLOWED_CHILD_MODULES:
        if name.startswith(allowed + "."):
            return True
    return False


def build_safe_globals() -> dict:
    """Return a globals dict with `__builtins__` stripped of dangerous names.

    Intended for the subprocess child to install via
    `globals().update(build_safe_globals())` before importing user code.
    """
    safe_builtins = {
        name: value
        for name, value in vars(builtins).items()
        if name not in BLOCKED_BUILTINS
    }
    return {"__builtins__": safe_builtins}
