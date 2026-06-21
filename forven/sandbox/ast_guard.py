"""AST-based static guard for AI-generated strategy source (P2-T02).

Single-pass walk over the parsed AST that records ALL violations without
bailing on the first. Never executes user code — uses `ast.parse` only.

Public API:
- :func:`scan_source` — scan an in-memory source string
- :func:`scan_file`   — read+scan a file from disk

Both return an :class:`AstReport`. `ok` is True iff no findings were
recorded. Forbidden categories: top-level imports of OS/network/file/
subprocess/dynamic-exec stdlib modules, dynamic execution constructs
(`eval`/`exec`/`compile`/`__import__('…')`/`getattr(__builtins__, …)`),
and size caps (file bytes + line count).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Hard caps. Configurable via forven.config.sandbox in a later phase.
MAX_FILE_BYTES: int = 100 * 1024  # 100 KB
MAX_LINES: int = 1500

FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {
        "os",
        "subprocess",
        "socket",
        "requests",
        "httpx",
        "urllib",
        "urllib2",
        "urllib3",
        "ctypes",
        "multiprocessing",
        "threading",
        "pathlib",
        "shutil",
        "tempfile",
        "pickle",
        "marshal",
        "importlib",
        # The `ta` technical-analysis library is permanently blocked at runtime by
        # the import tripwire in forven/__init__.py. Reject it here too so a
        # generated strategy that imports it fails fast during validation (and the
        # codegen retry can fix it) instead of crashing mid-backtest.
        "ta",
    }
)

FORBIDDEN_CALLS: frozenset[str] = frozenset(
    {
        "eval",
        "exec",
        "compile",
        # Filesystem / introspection builtins an honest trading strategy never
        # needs. `open` is the bare file primitive that lets generated code read
        # ~/.forven credentials/DB; globals/vars/locals expose module globals
        # (and thus __builtins__) used in sandbox-escape gadget chains.
        "open",
        "globals",
        "vars",
        "locals",
        "input",
        "breakpoint",
    }
)

# Dunder attributes that form the standard CPython sandbox-escape gadget chains
# (e.g. ``().__class__.__bases__[0].__subclasses__()`` or ``fn.__globals__``).
# A strategy that only computes indicators over OHLCV never touches these, so
# reaching for one is a strong signal of an escape attempt. The AST denylist is
# NOT a complete trust boundary (run untrusted strategies with the subprocess
# sandbox enabled) but closing these closes the obvious bypasses.
FORBIDDEN_ATTRS: frozenset[str] = frozenset(
    {
        "__subclasses__",
        "__bases__",
        "__base__",
        "__mro__",
        "__globals__",
        "__builtins__",
        "__getattribute__",
        "__subclasshook__",
        "__code__",
        "__closure__",
        "__import__",
        "__loader__",
        "__self__",
    }
)

FindingKind = Literal[
    "forbidden_import",
    "dynamic_exec",
    "file_too_large",
    "too_many_lines",
    "syntax_error",
]


@dataclass
class Finding:
    kind: FindingKind
    lineno: int
    col: int
    message: str
    node_repr: str


@dataclass
class AstReport:
    ok: bool
    findings: list[Finding] = field(default_factory=list)
    file_size_bytes: int = 0
    line_count: int = 0


class _GuardVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.findings: list[Finding] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in FORBIDDEN_IMPORTS:
                self.findings.append(
                    Finding(
                        kind="forbidden_import",
                        lineno=node.lineno,
                        col=node.col_offset,
                        message=f"Forbidden import: '{alias.name}'",
                        node_repr=ast.dump(node),
                    )
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        top = module.split(".")[0]
        if top in FORBIDDEN_IMPORTS:
            self.findings.append(
                Finding(
                    kind="forbidden_import",
                    lineno=node.lineno,
                    col=node.col_offset,
                    message=f"Forbidden import: 'from {module} import ...'",
                    node_repr=ast.dump(node),
                )
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func

        if isinstance(func, ast.Name) and func.id in FORBIDDEN_CALLS:
            self.findings.append(
                Finding(
                    kind="dynamic_exec",
                    lineno=node.lineno,
                    col=node.col_offset,
                    message=f"Forbidden call: '{func.id}(...)'",
                    node_repr=ast.dump(node),
                )
            )
        elif isinstance(func, ast.Name) and func.id == "__import__":
            # A dynamic import is safe ONLY when its argument is a CONSTANT string
            # naming a non-forbidden module — that is exactly equivalent to a plain
            # `import <name>` and is a common codegen idiom (`__import__("pandas")`).
            # A non-constant argument (the real obfuscation/exfil primitive) or a
            # forbidden module (os/socket/ctypes/…) stays blocked.
            const_mod: str | None = None
            if (
                node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                const_mod = node.args[0].value.split(".")[0]
            if const_mod is None or const_mod in FORBIDDEN_IMPORTS:
                self.findings.append(
                    Finding(
                        kind="dynamic_exec",
                        lineno=node.lineno,
                        col=node.col_offset,
                        message="Forbidden dynamic import: '__import__(...)'",
                        node_repr=ast.dump(node),
                    )
                )
        elif (
            isinstance(func, ast.Name)
            and func.id == "getattr"
            and node.args
            and isinstance(node.args[0], ast.Name)
            and node.args[0].id == "__builtins__"
        ):
            self.findings.append(
                Finding(
                    kind="dynamic_exec",
                    lineno=node.lineno,
                    col=node.col_offset,
                    message="Forbidden dynamic access: 'getattr(__builtins__, ...)'",
                    node_repr=ast.dump(node),
                )
            )

        # getattr/setattr/delattr/hasattr with a dunder string constant is the
        # string-form of the attribute-traversal escape (e.g.
        # ``getattr(obj, "__globals__")``); block it alongside the dotted form.
        if isinstance(func, ast.Name) and func.id in {
            "getattr",
            "setattr",
            "delattr",
            "hasattr",
        }:
            for _arg in node.args:
                if (
                    isinstance(_arg, ast.Constant)
                    and isinstance(_arg.value, str)
                    and (_arg.value in FORBIDDEN_ATTRS or _arg.value == "__builtins__")
                ):
                    self.findings.append(
                        Finding(
                            kind="dynamic_exec",
                            lineno=node.lineno,
                            col=node.col_offset,
                            message=(
                                f"Forbidden dynamic attribute access: "
                                f"'{func.id}(..., {_arg.value!r})'"
                            ),
                            node_repr=ast.dump(node),
                        )
                    )
                    break

        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in FORBIDDEN_ATTRS:
            self.findings.append(
                Finding(
                    kind="dynamic_exec",
                    lineno=node.lineno,
                    col=node.col_offset,
                    message=f"Forbidden attribute access: '.{node.attr}'",
                    node_repr=ast.dump(node),
                )
            )
        self.generic_visit(node)


def scan_source(source: str, file_size_bytes: int = 0) -> AstReport:
    """Scan a Python source string. *file_size_bytes* is reported as-given;
    when zero, it's filled in from `len(source.encode('utf-8'))`."""
    if file_size_bytes == 0 and source:
        file_size_bytes = len(source.encode("utf-8"))

    line_count = 0 if not source else source.count("\n") + (
        0 if source.endswith("\n") else 1
    )

    findings: list[Finding] = []

    if file_size_bytes > MAX_FILE_BYTES:
        findings.append(
            Finding(
                kind="file_too_large",
                lineno=0,
                col=0,
                message=(
                    f"File is {file_size_bytes} bytes, exceeds "
                    f"the {MAX_FILE_BYTES}-byte limit"
                ),
                node_repr="",
            )
        )

    if line_count > MAX_LINES:
        findings.append(
            Finding(
                kind="too_many_lines",
                lineno=0,
                col=0,
                message=(
                    f"Source has {line_count} lines, exceeds "
                    f"the {MAX_LINES}-line limit"
                ),
                node_repr="",
            )
        )

    if not source:
        return AstReport(
            ok=len(findings) == 0,
            findings=findings,
            file_size_bytes=file_size_bytes,
            line_count=line_count,
        )

    try:
        tree = ast.parse(source, mode="exec")
    except SyntaxError as exc:
        findings.append(
            Finding(
                kind="syntax_error",
                lineno=exc.lineno or 0,
                col=exc.offset or 0,
                message=f"SyntaxError: {exc.msg}",
                node_repr="",
            )
        )
        return AstReport(
            ok=False,
            findings=findings,
            file_size_bytes=file_size_bytes,
            line_count=line_count,
        )

    visitor = _GuardVisitor()
    visitor.visit(tree)
    findings.extend(visitor.findings)

    return AstReport(
        ok=len(findings) == 0,
        findings=findings,
        file_size_bytes=file_size_bytes,
        line_count=line_count,
    )


def scan_file(path: Path | str) -> AstReport:
    """Read *path* and scan it. UTF-8 with latin-1 fallback so we never
    raise UnicodeDecodeError out of the guard."""
    p = Path(path)
    raw = p.read_bytes()
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError:
        source = raw.decode("latin-1")
    return scan_source(source, file_size_bytes=len(raw))
