#!/usr/bin/env python3
"""Re-backtest the MACD-divergence paper strategies after the causal-swing fix.

The stored backtest metrics were computed with the OLD symmetric (lookahead-biased)
swing detection. This script re-runs backtests with the FIXED causal code and
prints a side-by-side comparison: OLD (biased) vs NEW (honest), plus quick_screen
gate status on the new results.

Each strategy is backtested with the SAME trade_mode that was used originally
(matched from stored metrics), so the comparison is apples-to-apples.
"""
from __future__ import annotations
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

os.environ.setdefault("FORVEN_API_URL", "http://127.0.0.1:8004")
os.environ.setdefault("FORVEN_API_KEY", "92ec5b339a6a980a8c3d6dc31b237ac4e9572a520921ce454fb5bf049839d7c0")
os.environ.setdefault("FORVEN_OPERATOR_KEY", "295dc8d02f34f301b6456ae19f4b5b02e8bddc815b124729c020d57dba573566")

from forven.agent import ForvenAgentClient

# (strategy_id, dataset, trade_mode) — trade_mode matched from stored metrics
STRATS = [
    ("S01517", "BTC/USDT-15m", "long_only"),
    ("S01760", "SOL/USDT-15m", "long_only"),
    ("S01766", "SOL/USDT-15m", "long_only"),
    ("S01767", "SOL/USDT-1h",  "long_only"),
    ("S01827", "ETH/USDT-1h",  "long_only"),
    ("S01830", "BTC/USDT-15m", "both"),
    ("S01932", "SOL/USDT-1h",  "both"),
    ("S01939", "SOL/USDT-4h",  "both"),
    ("S01946", "SOL/USDT-15m", "long_only"),
    ("S01947", "ETH/USDT-15m", "long_only"),
    ("S01990", "ETH/USDT-1h",  "both"),
    ("S01991", "ETH/USDT-4h",  "both"),
    ("S02000", "ETH/USDT-1h",  "both"),
    ("S02023", "WLD/USDT-15m", "both"),
]


def fetch_old_metrics() -> dict:
    fc = ForvenAgentClient()
    paper = fc.list_strategies(status="paper")
    items = paper if isinstance(paper, list) else (
        paper.get("items") or paper.get("strategies") or paper.get("data") or []
    )
    wanted = {s[0] for s in STRATS}
    out = {}
    for s in items:
        sid = s.get("id")
        if sid in wanted:
            out[sid] = {
                "symbol": s.get("symbol"),
                "timeframe": s.get("timeframe"),
                "metrics": s.get("metrics") or {},
            }
    return out


def run_one(sid: str, ds: str, mode: str):
    fc = ForvenAgentClient()  # fresh client per worker (thread-safe)
    t0 = time.time()
    try:
        r = fc.run_backtest(sid, ds, trade_mode=mode, compact=True)
        return sid, r, None, time.time() - t0
    except Exception as e:  # noqa: BLE001
        return sid, None, repr(e), time.time() - t0


def g(d: dict, k: str, default="–"):
    if not d:
        return default
    v = d.get(k, default)
    return default if v is None else v


def fmt(v, nd=2):
    if v in (None, "–") or isinstance(v, str):
        return str(v)
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def main() -> int:
    print("Fetching OLD (lookahead-biased) metrics from paper list...", flush=True)
    old = fetch_old_metrics()
    print(f"  matched {len(old)}/{len(STRATS)} old records\n", flush=True)

    print(f"Running {len(STRATS)} re-backtests (causal/honest) with 4 workers...", flush=True)
    results: dict = {}
    errors: dict = {}
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(run_one, sid, ds, mode): sid for sid, ds, mode in STRATS}
        for fut in as_completed(futs):
            sid, r, err, dur = fut.result()
            results[sid] = r
            errors[sid] = err
            mark = "OK " if err is None else "ERR"
            print(f"  [{mark}] {sid}  {dur:5.1f}s  {err or ''}", flush=True)
    print(f"  done in {time.time()-t_start:.1f}s\n", flush=True)

    # ---- comparison table ----
    print("=" * 132)
    print("RE-BACKTEST COMPARISON: OLD (symmetric/lookahead)  →  NEW (causal/honest)")
    print("=" * 132)
    hdr = (
        f"{'ID':<7} {'ASSET':<11} {'MODE':<9} | "
        f"{'IS tr':>5} {'IS PF':>6} {'IS Sh':>6} | "
        f"{'OOS tr':>6} {'OOS PF':>7} {'OOS Sh':>7} | "
        f"{'MaxDD':>6} {'TotRet':>7} | {'GATE':<14}"
    )
    print(hdr)
    print("-" * 132)

    summary_rows = []
    for sid, ds, mode in STRATS:
        om = old.get(sid, {}).get("metrics", {})
        o_is = om.get("in_sample") or {}
        o_oos = om.get("out_of_sample") or {}
        o_comb = om

        nr = results.get(sid) or {}
        n_is = nr.get("in_sample") or {}
        n_oos = nr.get("out_of_sample") or {}
        asset = nr.get("asset") or old.get(sid, {}).get("symbol") or "?"
        tf = old.get(sid, {}).get("timeframe") or ds.split("-")[-1]
        asset_label = f"{asset}/{tf}" if "/" not in str(asset) else f"{asset}-{tf}"

        # quick_screen on NEW compact result
        gate = "–"
        gate_reasons = ""
        if nr and not errors.get(sid):
            try:
                qs = ForvenAgentClient.quick_screen(nr)
                gate = "PASS" if qs.get("pass") else "FAIL"
                if not qs.get("pass"):
                    gate_reasons = "; ".join(qs.get("reasons") or [])
            except Exception as e:  # noqa: BLE001
                gate = f"ERR:{e}"

        err = errors.get(sid)
        if err:
            print(f"{sid:<7} {asset_label:<11} {mode:<9} | ERROR: {err}")
            summary_rows.append((sid, asset_label, mode, gate, False))
            continue

        line = (
            f"{sid:<7} {asset_label:<11} {mode:<9} | "
            f"{fmt(g(o_is,'total_trades'))}→{fmt(g(n_is,'total_trades')):>2} {fmt(g(o_is,'profit_factor'))}→{fmt(g(n_is,'profit_factor')):>3} {fmt(g(o_is,'sharpe'))}→{fmt(g(n_is,'sharpe')):>3} | "
            f"{fmt(g(o_oos,'total_trades'))}→{fmt(g(n_oos,'total_trades')):>3} {fmt(g(o_oos,'profit_factor'))}→{fmt(g(n_oos,'profit_factor')):>3} {fmt(g(o_oos,'sharpe'))}→{fmt(g(n_oos,'sharpe')):>3} | "
            f"{fmt(g(n_oos, 'max_drawdown_pct'), 3):>6} {fmt(g(n_oos, 'total_return_pct'), 3):>7} | {gate:<14}"
        )
        print(line)
        if gate_reasons:
            print(f"{'':>9} reasons: {gate_reasons}")
        summary_rows.append((sid, asset_label, mode, gate, gate == "PASS"))

    # ---- summary ----
    print("=" * 132)
    # summary_rows = (sid, asset, mode, gate_str, is_pass_bool)
    n_pass = sum(1 for r in summary_rows if r[4])
    n_fail = sum(1 for r in summary_rows if r[3] == "FAIL")
    n_err = sum(1 for r in summary_rows if str(r[3]).startswith("ERR"))
    print(f"\nSUMMARY: {len(summary_rows)} strategies re-backtested")
    print(f"  PASS quick_screen: {n_pass}")
    print(f"  FAIL quick_screen: {n_fail}")
    if n_err:
        print(f"  ERRORS:            {n_err}")
    print()
    if n_fail:
        print("Strategies that NO LONGER PASS gates (candidates for demotion/archive):")
        for r in summary_rows:
            if r[3] == "FAIL":
                print(f"  - {r[0]}  {r[1]}  ({r[2]})")
    if n_pass:
        print("Strategies that STILL PASS gates (honest edge confirmed):")
        for r in summary_rows:
            if r[3] == "PASS":
                print(f"  - {r[0]}  {r[1]}  ({r[2]})")

    # dump raw json for the record
    out_path = "/tmp/rebacktest_divergence_results.json"
    payload = {
        sid: {
            "dataset": ds,
            "trade_mode": mode,
            "old_metrics": old.get(sid, {}).get("metrics"),
            "new_compact": results.get(sid),
            "error": errors.get(sid),
        }
        for sid, ds, mode in STRATS
    }
    import json
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"\nRaw results written to: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
