# Fix: Custom Strategies 0 Trades in Paper (Unreachable Swing Divergence Bug)

**Date:** 2026-07-15
**Status:** Fixed & verified
**Affected:** 11 paper strategies (MACD-divergence family) + 4 sibling files
**Scope:** `forven/strategies/custom/` divergence family

---

## Symptom

Custom (non-builtin) strategies deployed in **paper** produced **0 live trades**, even though the frontend chart (`/paper-trades`) showed buy/sell signal arrows. Example: **S02023** (WLD/15m) showed a buy arrow ~05:45 GMT and sell ~07:30 GMT, but no trades were executed. The same affected ~15 custom strategies.

## Root Cause

> **Different from the previous session's diagnosis.** The previous session thought the cause was a `Signal.from_condition(False)` stub and "fixed" it by replacing the stub with `if i + 1 == n - 1:`. **That condition is structurally unreachable**, which is why the bug persisted.

### Two execution paths, two outcomes

| Path | Method | Used by | Condition | Reachable? |
|------|--------|---------|-----------|-----------|
| **Scalar** (live) | `generate_signal(df)` | Scanner for **execution** (`scanner.py:2804`) | `if i + 1 == n - 1` (swing at `n-2`) | ❌ NO |
| **Vectorized** (chart/backtest) | `generate_signals(df)` | Dashboard arrows + backtest (`scanner.py:~2819`) | `if i + 1 < n` (entry at `i+1`) | ✅ YES |

### Why the scalar condition is unreachable

Every affected strategy detected swing points with a **symmetric** window that looks `half` bars into the future:

```python
def _swing_points(self, series, window):
    half = max(window // 2, 2)
    for i in range(half, n - half):          # swings only detectable up to n-half-1
        seg = series.iloc[i - half : i + half + 1]  # looks FORWARD `half` bars
```

- Last detectable swing index = `n - half - 1`.
- Scalar requires swing at `n - 2`.
- Since `half ≥ 2`, `n - 2 > n - half - 1` **always** → the condition `i + 1 == n - 1` can never coincide with a detected swing → `entry_signal` stays `False` forever → **0 live trades**.

The vectorized path uses `i + 1 < n` (reachable) → arrows appear on chart + backtest produces trades. The vectorized path also **leaks future information** (a swing at `i` is only confirmable at `i + half`), so the backtest was **lookahead-biased** (overly optimistic).

### Evidence (real WLD 15m data, 104,327 bars)

- Vectorized: 567 long + 518 short entries
- Scalar: `entry_signal=False`
- Last detectable swing index = 104,323; scalar needs swing at 104,325 (`n-2`) → unreachable
- Gap between last swing's entry bar (104,321) and current bar (104,326) = 5 bars

## The Fix

Replace the **symmetric** `_swing_points` with a **causal** version (looks only at past + current bars):

```python
def _swing_points(self, series, window):
    """Causal swing detection — no forward lookahead."""
    n = len(series)
    result = pd.Series(0, index=series.index, dtype=int)
    if n < window:
        return result
    for i in range(window - 1, n):
        seg = series.iloc[i - window + 1 : i + 1]   # only past + current bar
        curr = series.iloc[i]
        if pd.isna(curr):
            continue
        if curr == seg.max() and (seg == curr).sum() == 1:
            result.iloc[i] = 1
        elif curr == seg.min() and (seg == curr).sum() == 1:
            result.iloc[i] = -1
    return result
```

A swing at `n - 2` is now confirmable using only bars up to `n - 2`, so the scalar `i + 1 == n - 1` condition becomes **reachable**. Both paths share `_swing_points`, so scalar and vectorized produce **identical last-bar signals** (backtest parity restored, no lookahead).

### Validation (causal variant, same WLD data)

- Scalar now reachable (swing at `n-2` detected)
- **Parity: 0 mismatches** over the last 500 bars between scalar last-bar entry and vectorized last-bar entry

## Files Modified

### Tier 1 — `_swing_points` symmetric → causal (mechanical fix, via `scripts/fix_swing_causal.py`)

These had the unreachable `i + 1 == n - 1` scalar + symmetric swing. The causal fix makes the condition reachable automatically.

| File | Strategy ID(s) | Gate |
|------|----------------|------|
| `wld_macd_div_opt.py` | S02023 | volume decline |
| `macd_divergence_reversal.py` | S01517 | none |
| `macd_divergence_sol_volume.py` | S01760/66/67 | volume spike |
| `macd_divergence_btc_taker.py` | S01830 | taker z-score |
| `macd_divergence_sol_1h_volume.py` | S01932 | volume spike |
| `macd_divergence_fixed_la.py` | S01939 | volume spike |
| `macd_div_fixed_la_sol.py` | S01946 | volume spike |
| `macd_div_fixed_la_eth.py` | S01947 | volume spike |
| `macd_div_fixed_la_taker_eth_v1.py` | S01990/91 | taker z-score |
| `macd_divergence_oi_confirmed_eth_v1.py` | S02000 | OI divergence |

### Tier 2 — Dual bug (scalar rewrite + vectorized range fix)

| File | Strategy ID | Extra fix |
|------|-------------|-----------|
| `macd_divergence_eth_1h_volume.py` | S01827 | Scalar rewrote to `i+1==n-1` loop pattern (was a stale-divergence list-comp w/o recency gate); vectorized `range(swing_win, n-swing_win)` → `range(swing_win, n)` |

### Tier 3 — Stub → real `generate_signal` (via @fixer)

These had a stub `Signal.from_condition(False)` AND the symmetric swing. After the causal swing fix, a real `generate_signal` was written mirroring each file's `generate_signals` (with its confirmation gate).

| File | Status | Gate |
|------|--------|------|
| `wld_macd_divergence_v1.py` | S02020 (archived) | volume decline |
| `macd_div_fixed_la_btc.py` | not in paper | volume spike |
| `macd_divergence_eth_4h_taker.py` | not in paper | taker z-score |
| `sol_macd_funding_divergence.py` | not in paper | funding + LS ratio |

## Verification

### Parity test script

**`scripts/test_signal_parity.py`** — verifies the scalar (live) path matches the vectorized (chart) path.

```bash
cd /home/hms/forven
.venv/bin/python scripts/test_signal_parity.py            # fast: last-bar parity + reachability
.venv/bin/python scripts/test_signal_parity.py --deep 300 # slow: parity over last 300 bars
.venv/bin/python scripts/test_signal_parity.py --all      # include non-paper divergence files
```

**Result (2026-07-15):** All 11 paper strategies → **0 mismatches** in deep parity (exit-priority aware).

> **Exit-priority semantics:** The scalar clears `entry_signal` when a MACD-histogram-zero-cross exit fires on the same bar (exit priority). The vectorized path keeps entry+exit separate for chart display. The parity test accounts for this: a bar with `vec_entry AND hist_zero_cross` is an expected `scalar=False`, not a mismatch.

### Backend

- Restarted: `Custom strategies loaded: 278 module(s)... 350 total types` (new code loaded)
- `scanner_execution_enabled: true`
- After restart, `entry=-` in logs is **correct** — no divergence signal on the current bar. Strategies will execute when a swing+divergence occurs (proven by the parity test).

## How to Detect This Bug in the Future

```bash
# Symmetric swing detection (the root cause pattern)
grep -rln "for i in range(half, n - half)" forven/strategies/custom/

# Unreachable scalar condition
grep -rln "if i + 1 == n - 1" forven/strategies/custom/

# Stub generate_signal (related, separate bug — caught by intake gate for new registrations)
grep -rln "Signal.from_condition(False" forven/strategies/custom/
.venv/bin/python -c "from forven.strategies.stub_detector import scan_custom_directory; print(scan_custom_directory())"
```

**Any output from the first two greps = this bug is present.** The fix is causal `_swing_points`.

## ⚠️ Important Caveat — Re-backtesting Required

The strategies were promoted to paper based on backtests computed with the **symmetric (lookahead-biased)** swing detection. The fix changes both paths to causal, so:

- **Stored backtest metrics are now stale/optimistic.** The lookahead was inflating results (e.g., WLD long entries went from 567 symmetric → 792 causal — signal count and all metrics shift).
- **Live performance will now match a causal (honest) backtest**, which may be worse than the biased metrics suggested.
- **Recommended:** Re-backtest all 11 paper strategies (`forven.agent backtest --strategy SXXXXX --dataset <SYMBOL>-<tf> --compact`) to get honest metrics. Some may no longer pass gates and should be demoted/archived.

Re-backtesting is operational follow-up, not part of the code fix.

## Tools Created

- `scripts/fix_swing_causal.py` — AST-based, idempotent transform of `_swing_points` symmetric → causal. Documented with root cause. Re-runnable (skips already-causal files).
- `scripts/test_signal_parity.py` — parity test (scalar vs vectorized) for all paper divergence strategies. Fast + deep modes.

## Key Lesson

> When `generate_signal()` (scalar/live) and `generate_signals()` (vectorized/chart) diverge, the chart shows arrows but no trades execute. A "real-looking" implementation is not enough — the scalar's entry condition must be **structurally reachable** given the indicator's detection window. **Symmetric (forward-looking) swing detection makes recent swings undetectable in real-time**, so any scalar condition requiring a swing near the current bar is unreachable. The fix is **causal detection** (look backwards only), which also removes lookahead bias from the backtest.

## Related

- `AGENTS.md` → "PITFALL: generate_signal() Stub" section (documents the stub variant of this bug)
- `forven/scanner.py:2804` — scalar `generate_signal(df)` call (execution)
- `forven/scanner.py:~2819` — `_latest_directional_signals` → vectorized `generate_signals` (dashboard)
- `forven/strategies/base.py` — `Signal`, `DirectionalSignals`, `BaseStrategy`
