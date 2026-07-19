#!/usr/bin/env python3
"""Fix the unreachable-swing bug across the MACD-divergence strategy family.

ROOT CAUSE
----------
Every affected strategy detects swing points with a SYMMETRIC window:

    half = window // 2
    for i in range(half, n - half):          # swings only up to index n-half-1
        seg = series.iloc[i-half : i+half+1] # looks FORWARD `half` bars

The live scanner calls the SCALAR ``generate_signal(df)`` for execution, which
fires entry only when ``i + 1 == n - 1`` (swing at index n-2). But swings are
only detectable up to ``n - half - 1`` and ``half >= 2`` (or 3), so
``n - 2 > n - half - 1`` always => the condition is structurally UNREACHABLE
=> ``entry_signal`` stays False forever => 0 live trades.

The vectorized ``generate_signals()`` (used for chart arrows + backtest) uses
``if i + 1 < n`` which IS reachable, so arrows/trades appear in backtest but
never execute live. (The vectorized path also leaks future info — a swing at
``i`` is only confirmable at ``i + half`` — so the backtest is lookahead-biased.)

FIX
---
Replace the symmetric ``_swing_points`` with a CAUSAL version that only looks
at past + current bars (``i - window + 1`` .. ``i``). A swing at ``n - 2`` is
then confirmable using bars up to ``n - 2``, so the scalar ``i + 1 == n - 1``
condition becomes reachable. Both paths share ``_swing_points``, so scalar and
vectorized produce identical last-bar signals (backtest parity, no lookahead).

This script is IDEMPOTENT: files already using causal detection are skipped.
"""
from __future__ import annotations

import ast
import pathlib
import sys

BASE = pathlib.Path("forven/strategies/custom")

# Every file that has a symmetric _swing_points (range(half, n - half)).
TARGET_FILES = [
    "macd_divergence_btc_taker.py",
    "macd_divergence_eth_1h_volume.py",
    "macd_divergence_eth_4h_taker.py",
    "macd_divergence_fixed_la.py",
    "macd_divergence_oi_confirmed_eth_v1.py",
    "macd_divergence_reversal.py",
    "macd_divergence_sol_1h_volume.py",
    "macd_divergence_sol_volume.py",
    "macd_div_fixed_la_btc.py",
    "macd_div_fixed_la_eth.py",
    "macd_div_fixed_la_sol.py",
    "macd_div_fixed_la_taker_eth_v1.py",
    "sol_macd_funding_divergence.py",
    "wld_macd_divergence_v1.py",
    "wld_macd_div_opt.py",  # already fixed — script will skip (idempotent)
]

CAUSAL_NUMPY = '''    def _swing_points(self, series, window):
        """Causal swing detection — 1 (high), -1 (low), 0 (neither). No forward lookahead.

        A bar is a swing high/low if it is the unique max/min in the preceding
        (window-1) bars plus itself. Only past and current bars are inspected,
        so a swing at index ``i`` is confirmable at bar ``i`` itself — this
        makes the live scalar entry condition ``i + 1 == n - 1`` reachable and
        keeps the vectorized path free of lookahead bias.
        """
        left_idx = series.index
        arr = series.values
        n = len(arr)
        if n < window:
            return pd.Series(np.zeros(n, dtype=int), index=left_idx)
        result = np.zeros(n, dtype=int)
        for i in range(window - 1, n):
            seg = arr[i - window + 1 : i + 1]
            if arr[i] == np.max(seg) and np.sum(seg == arr[i]) == 1:
                result[i] = 1
            elif arr[i] == np.min(seg) and np.sum(seg == arr[i]) == 1:
                result[i] = -1
        return pd.Series(result, index=left_idx)
'''

CAUSAL_PANDAS = '''    def _swing_points(self, series, window):
        """Causal swing detection — 1 (high), -1 (low), 0 (neither). No forward lookahead.

        A bar is a swing high/low if it is the unique max/min in the preceding
        (window-1) bars plus itself. Only past and current bars are inspected,
        so a swing at index ``i`` is confirmable at bar ``i`` itself — this
        makes the live scalar entry condition ``i + 1 == n - 1`` reachable and
        keeps the vectorized path free of lookahead bias.
        """
        n = len(series)
        result = pd.Series(0, index=series.index, dtype=int)
        if n < window:
            return result
        for i in range(window - 1, n):
            seg = series.iloc[i - window + 1 : i + 1]
            curr = series.iloc[i]
            if pd.isna(curr):
                continue
            if curr == seg.max() and (seg == curr).sum() == 1:
                result.iloc[i] = 1
            elif curr == seg.min() and (seg == curr).sum() == 1:
                result.iloc[i] = -1
        return result
'''


def detect_variant(method_src: str) -> str:
    """Return 'numpy' if the method uses series.values/np.max, else 'pandas'."""
    if "series.values" in method_src or "np.max" in method_src:
        return "numpy"
    return "pandas"


def is_already_causal(method_src: str) -> bool:
    return "range(window - 1, n)" in method_src or "range(window-1, n)" in method_src


def transform(path: pathlib.Path) -> str:
    src = path.read_text()
    tree = ast.parse(src)
    target_node = None
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_swing_points":
            target_node = node
            break
    if target_node is None:
        return f"SKIP {path.name}: no _swing_points method"

    old_segment = ast.get_source_segment(src, target_node)
    if is_already_causal(old_segment):
        return f"SKIP {path.name}: already causal"

    variant = detect_variant(old_segment)
    new_segment = CAUSAL_NUMPY if variant == "numpy" else CAUSAL_PANDAS

    # ast.get_source_segment includes the leading "def" line but NOT the
    # method decorator/indentation prefix. We need to replace from the start of
    # the "def" line. Find the exact text span via line offsets.
    start_line = target_node.lineno  # 1-indexed
    end_line = target_node.end_lineno
    lines = src.splitlines(keepends=True)
    # Replace lines [start_line-1 : end_line] with the new method (already
    # indented at 4 spaces, matching class-body methods).
    prefix = lines[start_line - 1][: len(lines[start_line - 1]) - len(lines[start_line - 1].lstrip())]
    # The CAUSAL_* constants are already indented 4 spaces; ensure they match
    # the file's indentation (class methods = 4 spaces). If prefix is empty or
    # differs, re-indent.
    new_text = new_segment
    # sanity: new_text is indented with 4 spaces. Re-indent to match prefix if needed.
    if prefix and prefix != "    ":
        new_text = "\n".join(
            (prefix + ln[4:]) if ln.startswith("    ") else ln
            for ln in new_text.split("\n")
        )

    new_lines = lines[: start_line - 1] + [new_text] + lines[end_line:]
    new_src = "".join(new_lines)

    # Validate it still parses.
    try:
        ast.parse(new_src)
    except SyntaxError as e:
        return f"ERROR {path.name}: syntax error after edit: {e}"

    path.write_text(new_src)
    return f"FIXED {path.name} ({variant} variant)"


def main() -> int:
    if not BASE.exists():
        print(f"ERROR: base dir not found: {BASE}", file=sys.stderr)
        return 1
    rc = 0
    for fn in TARGET_FILES:
        p = BASE / fn
        if not p.exists():
            print(f"MISS {fn}")
            continue
        print(transform(p))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
