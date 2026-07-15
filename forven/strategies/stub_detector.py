"""Detect `generate_signal()` stub patterns that cause silent 0-trade failures.

A common codegen error: the vectorized `generate_signals()` is implemented correctly
but the per-bar `generate_signal()` is left as a no-op stub:

    def generate_signal(self, df: pd.DataFrame) -> Signal:
        return Signal.from_condition(False, df=df, direction="long", confidence=0.0)

The live scanner calls `generate_signal()`, so this stub means the strategy will
NEVER produce an entry signal in paper trading — even though backtests and charts
(via `generate_signals()`) show arrows and trades.

This module provides detection that can be used both at registration time
(catching the stub before the strategy enters the pipeline) and as a periodic
health check (scanning already-registered custom files for stubs that slipped
through).
"""

from __future__ import annotations

import ast
import logging
from pathlib import Path

log = logging.getLogger("forven.strategies.stub_detector")

# ---------------------------------------------------------------------------
# Core detection
# ---------------------------------------------------------------------------


def detect_generate_signal_stub(source: str | Path) -> str | None:
    """Check a strategy source file for a ``generate_signal`` stub.

    Returns a human-readable reason string if a stub is found, or ``None`` if
    the implementation looks real (or the file cannot be parsed).
    """
    if isinstance(source, Path):
        try:
            source = source.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            log.debug("Cannot read %s for stub check: %s", source, exc)
            return None

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None  # syntax errors are caught elsewhere

    visitor = _GenerateSignalStubVisitor()
    visitor.visit(tree)
    return visitor.stub_reason


class _GenerateSignalStubVisitor(ast.NodeVisitor):
    """Walk the AST looking for ``generate_signal`` methods that are stubs.

    A method is considered a stub when its body consists of exactly one
    ``return`` statement whose value is a call to ``Signal.from_condition``
    (or any ``Signal(…)`` constructor) where the first positional argument
    is the literal ``False`` *and* the method body contains no other
    meaningful logic (no local variables, no attribute reads, no other
    function calls besides the single return).

    Our tolerance rules:
    - Extra blank lines / comments / docstrings between ``def`` and ``return``
      are fine — they don't make the method "real".
    - The single ``return Signal(…)`` pattern with ``False`` as the entry
      condition IS the core stub signature.
    - A method that reads ``self.params``, calls helpers, computes values,
      or has multiple statements is NOT flagged.
    """

    def __init__(self) -> None:
        super().__init__()
        self.stub_reason: str | None = None
        self._current_class: str | None = None

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        old_class = self._current_class
        self._current_class = node.name
        self.generic_visit(node)
        self._current_class = old_class

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if self.stub_reason is not None:
            return  # already found one

        if node.name != "generate_signal":
            return

        # Don't flag if we already have a reason (first stub wins).
        body = _strip_docstring_and_empty(node.body)
        if not body:
            return  # empty body — weird but not a stub

        # Pattern 1: single return statement
        if len(body) == 1 and isinstance(body[0], ast.Return):
            ret = body[0]
            if _is_signal_false_call(ret.value):
                self.stub_reason = (
                    f"generate_signal() in class '{self._current_class or '<unknown>'}' "
                    f"is a stub — returns Signal(False) unconditionally. "
                    f"This will cause 0 trades in paper trading even though backtests "
                    f"and charts show signals. Implement real per-bar logic that mirrors "
                    f"generate_signals()."
                )
                return

        # Pattern 2: multi-line but all just computing False (paranoid check)
        meaningful = [
            stmt
            for stmt in body
            if not isinstance(stmt, ast.Return)
        ]
        if not meaningful and len(body) >= 1:
            # All statements are return stmts — check the last one
            last = body[-1]
            if isinstance(last, ast.Return) and _is_signal_false_call(last.value):
                self.stub_reason = (
                    f"generate_signal() in class '{self._current_class or '<unknown>'}' "
                    f"appears to be a stub (only return statements, ending with "
                    f"Signal(False)). Implement real per-bar logic."
                )
                return


def _is_signal_false_call(node: ast.expr | None) -> bool:
    """Return True if *node* is a call that always produces ``entry_signal=False``.

    Matches:
        Signal.from_condition(False, ...)
        Signal(False, ...)
        Signal(entry_signal=False, ...)
    """
    if node is None:
        return False

    # Unwrap .from_condition() → Signal.from_condition(False, ...)
    if isinstance(node, ast.Call):
        func = node.func
        # Signal.from_condition(False, ...)
        if (
            isinstance(func, ast.Attribute)
            and isinstance(func.value, ast.Name)
            and func.value.id == "Signal"
            and func.attr == "from_condition"
        ):
            if _first_arg_is_false(node):
                return True
        # Signal(False, ...)
        if isinstance(func, ast.Name) and func.id == "Signal":
            if _first_arg_is_false(node):
                return True
            # Signal(entry_signal=False, ...) — check keyword
            for kw in node.keywords:
                if kw.arg == "entry_signal" and _is_false_literal(kw.value):
                    # Also check exit_signal if present
                    exit_false = True
                    for kw2 in node.keywords:
                        if kw2.arg == "exit_signal":
                            exit_false = _is_false_literal(kw2.value)
                            break
                    if exit_false:
                        return True

    return False


def _first_arg_is_false(call: ast.Call) -> bool:
    """Return True if the first positional argument to *call* is the literal ``False``."""
    if call.args:
        return _is_false_literal(call.args[0])
    return False


def _is_false_literal(node: ast.expr) -> bool:
    """Return True if *node* is the literal ``False`` or ``None`` (but not ``True``)."""
    if isinstance(node, ast.Constant):
        return node.value is False or node.value is None
    # NameConstant is Python 3.7 and earlier; ast.Constant handles 3.8+
    if isinstance(node, getattr(ast, "NameConstant", ())):
        return node.value is False  # type: ignore[union-attr]
    return False


def _strip_docstring_and_empty(body: list[ast.stmt]) -> list[ast.stmt]:
    """Remove leading docstring and ``pass`` / ``...`` stmts from a function body."""
    result: list[ast.stmt] = []
    for stmt in body:
        # Skip docstring (first string expression)
        if (
            not result
            and isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        ):
            continue
        # Skip bare pass / ellipsis
        if isinstance(stmt, ast.Pass) or (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and stmt.value.value is Ellipsis
        ):
            continue
        result.append(stmt)
    return result


# ---------------------------------------------------------------------------
# Bulk check — used by monitoring
# ---------------------------------------------------------------------------


def scan_custom_directory(custom_dir: str | Path | None = None) -> list[tuple[str, str]]:
    """Scan all .py files in the custom strategy directory for stubs.

    Returns a list of ``(filename, reason)`` tuples for each file containing
    a stub.  Empty list means all clean.
    """
    if custom_dir is None:
        from forven.strategies import custom as _custom_pkg

        paths = _custom_pkg.__path__
        if not paths:
            return []
        custom_dir = Path(paths[0])
    else:
        custom_dir = Path(custom_dir)

    if not custom_dir.is_dir():
        return []

    findings: list[tuple[str, str]] = []
    for py_file in sorted(custom_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue
        reason = detect_generate_signal_stub(py_file)
        if reason:
            findings.append((py_file.name, reason))

    return findings
