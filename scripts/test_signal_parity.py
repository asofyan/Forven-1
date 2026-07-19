#!/usr/bin/env python3
"""Parity test: verify the scalar ``generate_signal()`` (live execution path)
matches the vectorized ``generate_signals()`` (chart/backtest path) on the last
bar, for every MACD-divergence custom strategy affected by the
unreachable-swing bug.

BACKGROUND
----------
The live scanner calls ``generate_signal(df)`` for EXECUTION
(forven/scanner.py:2804), while the dashboard/chart calls ``generate_signals()``
(scanner.py ~2819 via ``_latest_directional_signals``).  If these two disagree,
the chart shows buy/sell arrows but no trades execute (0 live trades).

ROOT CAUSE THAT WAS FIXED
-------------------------
``_swing_points`` used a SYMMETRIC window ``range(half, n - half)`` so swings
were only detectable up to index ``n - half - 1``.  The scalar entry condition
``i + 1 == n - 1`` (swing at ``n - 2``) was therefore UNREACHABLE
(``n - 2 > n - half - 1`` for ``half >= 2``) → ``entry_signal`` always False.
Fix: causal ``_swing_points`` (looks only at past + current bars) so a swing at
``n - 2`` is confirmable → scalar becomes reachable and matches vectorized.

USAGE
-----
    # Fast check (instant): last-bar parity + reachability + entry counts
    .venv/bin/python scripts/test_signal_parity.py

    # Deep check (slower): verify scalar==vectorized over the last N bars
    .venv/bin/python scripts/test_signal_parity.py --deep 200

    # Include non-paper divergence files too (the stub-fixed ones)
    .venv/bin/python scripts/test_signal_parity.py --all
"""
from __future__ import annotations

import argparse
import importlib
import json
import pathlib
import sqlite3
import sys
import traceback

import pandas as pd

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB = pathlib.Path.home() / ".forven" / "forven.db"
DATA = ROOT / "data" / "ohlcv"


def paper_strategies() -> list[dict]:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT display_id, runtime_type, symbol, timeframe, params, source_ref
        FROM strategies
        WHERE (status='paper' OR stage='paper')
          AND (runtime_type LIKE 'macd_div%' OR runtime_type LIKE 'wld_macd%')
        ORDER BY display_id
        """
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        if not r["source_ref"]:
            continue  # sibling sharing another row's file — skip duplicate
        out.append(dict(r))
    return out


def nonpaper_divergence_files() -> list[dict]:
    """Divergence-family files not (necessarily) in paper, for --all mode."""
    files = [
        ("macd_divergence_eth_4h_taker", "macd_divergence_eth_4h_taker.py", "ETH/USDT", "4h"),
        ("macd_div_fixed_la_btc", "macd_div_fixed_la_btc.py", "BTC/USDT", "15m"),
        ("sol_macd_funding_divergence", "sol_macd_funding_divergence.py", "SOL/USDT", "4h"),
        ("wld_macd_div_v1", "wld_macd_divergence_v1.py", "WLD/USDT", "15m"),
    ]
    return [
        {
            "display_id": "(nonpaper)",
            "runtime_type": rt,
            "symbol": sym,
            "timeframe": tf,
            "params": None,
            "source_ref": str(ROOT / "forven" / "strategies" / "custom" / fn),
        }
        for rt, fn, sym, tf in files
    ]


def load_class(source_ref: str):
    p = pathlib.Path(source_ref)
    modname = f"_parity_test_{p.stem}"
    spec = importlib.util.spec_from_file_location(modname, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cls = getattr(mod, "STRATEGY_CLASS", None)
    if cls is None:
        # fall back: find BaseStrategy subclass in module
        from forven.strategies.base import BaseStrategy

        for v in vars(mod).values():
            if isinstance(v, type) and issubclass(v, BaseStrategy) and v is not BaseStrategy:
                cls = v
                break
    return cls


def data_path(symbol: str, timeframe: str) -> pathlib.Path:
    sym = symbol.upper().replace("/USDT", "").replace("-USDT", "")
    return DATA / f"{sym}-USDT" / f"{timeframe}.parquet"


def load_data(symbol: str, timeframe: str) -> pd.DataFrame:
    p = data_path(symbol, timeframe)
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_parquet(p)
    if "timestamp" in df.columns:
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def latest_directional_entry(ds) -> bool:
    """True if the vectorized path has any entry on the LAST bar."""
    le = bool(ds.long_entries.iloc[-1]) if len(ds.long_entries) else False
    se = bool(ds.short_entries.iloc[-1]) if len(ds.short_entries) else False
    return le or se


def reachability(strategy, df, swing_param="swing_lookback", swing_default=8) -> tuple[bool, int, int]:
    """Can swing detection reach near the end? (proves the causal fix works).

    Before the fix (symmetric window) the last detectable swing was at
    ``n - half - 1`` (stuck `half` bars from the end) so the scalar entry
    condition ``i + 1 == n - 1`` (swing at n-2) was UNREACHABLE.  After the
    causal fix, swings are detectable right up to ``n - 1``.

    Returns (reaches_end, max_swing_idx, n).  ``reaches_end`` is True when the
    most recent swing is within the last ``window`` bars (i.e. detection is not
    stuck `half` bars back — the scalar CAN fire on a current-bar swing).
    """
    p = strategy.params if getattr(strategy, "params", None) else strategy.default_params
    win = int(p.get(swing_param, swing_default))
    swings = strategy._swing_points(df["close"], win)
    n = len(df)
    swing_idx = df.index[swings != 0].tolist()
    max_swing = max(swing_idx) if swing_idx else -1
    reaches_end = max_swing >= n - win  # detection reaches the last `window` bars
    return reaches_end, max_swing, n


def deep_parity(strategy, df, params, n_bars: int) -> tuple[int, int, list]:
    """Compare scalar entry vs vectorized last-bar entry over the last n_bars.

    To keep it fast we only invoke the (slow, O(n)) scalar on:
      - every bar where the vectorized path fires (the interesting case)
      - a 1-in-10 sample of non-firing bars (to catch false positives)
    Returns (mismatches, checks, sample_mismatch_bars).
    """
    n = len(df)
    start = max(0, n - n_bars)
    ds = strategy.generate_signals(df)
    long_e = ds.long_entries.fillna(False).astype(bool).values
    short_e = ds.short_entries.fillna(False).astype(bool).values
    vec_entry = long_e | short_e
    # The scalar (execution path) applies exit-priority: on a bar where both an
    # entry and a MACD-histogram-zero-cross exit fire, it clears the entry. The
    # vectorized path keeps entry+exit separate for chart display, and its
    # long_exits/short_exits ALSO include opposite-divergence exits that the
    # scalar does NOT use. So we compute the scalar's EXACT exit condition
    # (hist zero-cross) to derive the expected scalar entry decision.
    try:
        p = strategy.params if getattr(strategy, "params", None) else strategy.default_params
        _f = int(p.get("fast", 12)); _s = int(p.get("slow", 26)); _sig = int(p.get("signal", 9))
        _hist = strategy._macd_histogram(df["close"], _f, _s, _sig)
        _zc = ((_hist.shift(1) < 0) & (_hist >= 0)) | ((_hist.shift(1) > 0) & (_hist <= 0))
        hist_zc = _zc.fillna(False).astype(bool).values
    except Exception:
        hist_zc = vec_entry  # fallback: assume no exit-priority suppression

    mism = 0
    checks = 0
    bad = []
    # Slice to a recent window for speed: causal swing detection + ewm MACD
    # converge quickly, so the last-bar decision on a ~600-bar slice ending at
    # k matches the full-history decision (the scanner passes full history, but
    # only the recent bars affect the last-bar signal).
    window = 600
    cls = type(strategy)
    for k in range(start, n):
        fires = bool(vec_entry[k])
        sampled = fires or ((k - start) % 10 == 0)
        if not sampled:
            continue
        lo = max(0, k - window + 1)
        sub = df.iloc[lo : k + 1].copy()
        s2 = cls("t", dict(params))
        try:
            sg = s2.generate_signal(sub)
        except Exception as e:
            mism += 1
            bad.append((k, "EXC", str(e)[:60]))
            continue
        checks += 1
        # Expected scalar decision: entry only if vec fires AND no hist zero-cross
        # (the scalar's actual exit-priority condition).
        expected = fires and not bool(hist_zc[k])
        if bool(sg.entry_signal) != expected:
            mism += 1
            bad.append((k, f"scalar={bool(sg.entry_signal)} expected={expected} vec={fires} zc={bool(hist_zc[k])}"))
    return mism, checks, bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--deep", type=int, default=0, help="verify parity over last N bars (slow)")
    ap.add_argument("--all", action="store_true", help="also test non-paper divergence files")
    args = ap.parse_args()

    strats = paper_strategies()
    if args.all:
        strats = strats + nonpaper_divergence_files()

    print(f"{'ID':<10} {'symbol/tf':<12} {'vec L/S':<12} {'scalar':<16} {'swing@n-2':<10} {'parity':<8}")
    print("-" * 78)

    rc = 0
    for s in strats:
        sid = s["display_id"]
        sym = s["symbol"]
        tf = s["timeframe"]
        try:
            cls = load_class(s["source_ref"])
        except Exception as e:
            print(f"{sid:<10} {sym+'/'+tf:<12} IMPORT-FAIL: {e}")
            rc = 1
            continue

        df = load_data(sym, tf)
        if df.empty:
            print(f"{sid:<10} {sym+'/'+tf:<12} NO DATA FILE ({data_path(sym,tf)})")
            continue

        params = json.loads(s["params"]) if s["params"] else {}
        params["_asset"] = sym
        try:
            inst = cls(sid, params)
        except Exception as e:
            print(f"{sid:<10} {sym+'/'+tf:<12} INSTANTIATE-FAIL: {e}")
            rc = 1
            continue

        try:
            ds = inst.generate_signals(df)
            n_long = int(ds.long_entries.sum())
            n_short = int(ds.short_entries.sum())
            sig = inst.generate_signal(df)
            reach = reachability(inst, df)
        except Exception as e:
            print(f"{sid:<10} {sym+'/'+tf:<12} RUN-FAIL: {e}")
            traceback.print_exc()
            rc = 1
            continue

        vec_last = latest_directional_entry(ds)
        scalar_entry = bool(sig.entry_signal)
        last_parity = "OK" if vec_last == scalar_entry else "MISMATCH"
        if last_parity == "MISMATCH":
            rc = 1

        reaches_end, max_swing, n_bars = reach
        deep_str = ""
        if args.deep:
            m, c, bad = deep_parity(inst, df, params, args.deep)
            deep_str = f"deep:{c}chk/{m}mism"
            if m:
                rc = 1
                deep_str += " ❌"
                deep_str += f" e.g. {bad[:2]}"
            else:
                deep_str += " ✅"

        print(
            f"{sid:<10} {sym+'/'+tf:<12} {n_long}/{n_short:<10} "
            f"entry={scalar_entry!s:<5} dir={sig.direction:<6} "
            f"{'YES' if reaches_end else 'NO':<6} (maxsw={max_swing},n={n_bars}) "
            f"{last_parity:<8} {deep_str}"
        )

    print("-" * 78)
    print("Legend: vec L/S = vectorized long/short entry counts; scalar = live last-bar signal;")
    print("        swing@n-2 = is a swing at n-2 detectable (scalar can fire)? YES=good;")
    print("        parity = scalar last-bar entry == vectorized last-bar entry.")
    if args.deep:
        print("        deep = scalar vs vectorized over last N bars (firing bars + 1/10 sample).")
    print()
    print("PASS" if rc == 0 else "FAIL — see mismatches above")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
