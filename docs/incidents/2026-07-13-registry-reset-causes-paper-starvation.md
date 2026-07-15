# Incident: Registry `reset()` Causes Universal Paper Trading Starvation

**Date:** 2026-07-13
**Severity:** Critical (systemic, affects all paper-stage strategies)
**Root Cause:** `reset()` in `forven/agents/tools_backtesting.py:553` destroys `_TYPE_MAP`, creating a vulnerability window where every runtime type — including builtins like `ema_cross` and `donchian` — vanishes from the registry. Concurrent scanner access during this window sees "runtime type 'XYZ' is not registered" for every strategy and permanently skips them on the kernel execution path.

---

## Symptoms

- **22 out of 31 paper-stage strategies had zero trades** despite running on 15m-1h timeframes for days.
- No `SKIPPED`, `BLOCKED`, or `quarantine` messages in scanner logs — strategies loaded fine but never entered positions.
- Live scanner logs showed `entry=- | exit=-` for all strategies every 15-minute scan cycle.
- `generate_signals()` on the custom strategy class **did produce valid entry signals** when called directly (14 signals for S01517 on BTC 15m over 5 days), proving parameter tightness was not the issue.

## Root Cause Analysis

### The Trigger

`forven/agents/tools_backtesting.py:553` calls `registry.reset()` before registering a newly written strategy file:

```python
def register_strategy(...):
    # ...
    from forven.strategies.registry import reset, discover, _TYPE_MAP
    reset()  # ← DESTROYS _TYPE_MAP for ALL types
    registration = register_custom_strategy_file(...)
    discover()  # ← restores full _TYPE_MAP
```

### The Vulnerability Window

`reset()` (defined at `registry.py:997`) clears:
- `_TYPE_MAP` — all 350+ type→class mappings
- `_registry` — all instantiated strategies
- `_builtin_discovered`, `_custom_discovered`, `_discovered` flags
- `_BAD_ROW_LOGGED` — dedup protection

Then `register_custom_strategy_file()` calls `discover(include_custom=False)` which loads **only builtins** (~75 types). Between this partial re-discovery and the final `discover()` call at line 567, **every custom type is missing from `_TYPE_MAP`**.

If the scanner's `get_active()` cache expires during this window (it does — the scanner polls every 15 minutes), it calls `_load_db_strategies()` which calls `resolve_runtime_type()` for each strategy. Every type that is not a builtin comes back as "not registered":

```
Jul 09 07:15:55 [WARNING] Skipping bad strategy row S01517:
    runtime type 'macd_divergence_reversal' is not registered
Jul 10 14:50:53 [WARNING] Skipping bad strategy row S00986:
    runtime type 'ema_cross' is not registered   ← BUILTIN!
```

### Why Builtins Also Failed

On process restarts (Jul 9 08:41, Jul 10 14:50, Jul 11 10:45), the `_load_db_strategies()` code path at `registry.py:795` was called before any `discover()` had run. While `scanner.py:7870` does call `discover()` before `get_active()`, other call sites (like the per-strategy execution at `scanner.py:2764`) call `get_active().get(strat_id)` without `discover()`.

### Why Existing Trades Survived

Strategies that had ALREADY recorded paper trades before the registry failure (S00986, S01057, S01922) continued to have their open positions managed — the kernel could still close/refresh trades whose recorded DB rows already existed. But NO new entries could be opened because the kernel path returned `KERNEL_SKIP_SCAN` (transient) for the unregistered type — which deliberately prevents the legacy fallback from running.

### Why Strategies Never Recovered

The kernel execution path (`manage_positions_via_kernel`) re-simulates the full strategy history every scan. It uses a `fresh_cutoff` of the last 1 bar (default `paper_kernel_fill_now_max_bars=1`) to decide which entries to open. Once an entry signal's bar is more than 1 bar behind the present, it is treated as "stale" and left as a chart trigger only — never opened. So by the time the registry recovered days later, **all 14 entry signals that S01517 had generated were permanently past the fresh window**.

### Evidence

```
# Direct test of S01517's generate_signals() with current data showed 14 entries:
# All AFTER paper start date (Jul 7), none older than fresh_cutoff

2026-07-08 06:45:00 LONG  @ $62,628  ← missed, stale by Jul 12
2026-07-08 13:30:00 LONG  @ $61,935  ← missed
2026-07-08 23:00:00 SHORT @ $62,298  ← missed
...
2026-07-12 20:00:00 SHORT @ $64,161  ← missed
```

These signals were perfectly valid. The strategy was working. The registry just never delivered them to the kernel.

---

## Timeline

| Date | Event |
|------|-------|
| Jul 7 22:26 | S01517 reaches paper stage |
| Jul 8 06:45 | First valid divergence signal — never traded |
| Jul 9 07:13 | Full discover OK (266 types) |
| **Jul 9 07:15** | **Agent `register_strategy` calls `reset()` → scanner sees partial registry → "not registered" for ALL custom types** |
| Jul 9 07:15-11 | Multiple scanner ticks fail for all custom strategies |
| Jul 9-11 | Every `register_strategy` invocation repeats the same pattern |
| Jul 9 08:41, Jul 10 14:50, Jul 11 10:45 | Process restarts → `get_active()` called before `discover()` → builtins also fail |
| Jul 13 04:55 | Fix applied + backend restarted + paper book reset |

---

## Fix Applied

### 1. Removed `reset()` from `tools_backtesting.py:553`

`register_custom_strategy_file()` already calls `discover(include_custom=False)` which only loads builtins — custom types are never touched. The `reset()` call was therefore unnecessary and harmful.

**File:** `forven/agents/tools_backtesting.py`
**Change:** Removed `reset()` call and the `reset` import. The flow is now:
1. Import the new module directly (targeted)
2. Call `register_custom_strategy_file()` which handles registration + `discover(include_custom=False)`
3. Call full `discover()` to pick up any additional custom files

### 2. Paper Book Reset

Set `paper:book_reset_at` in KV store to `2026-07-13T04:54:23+00:00` so the kernel's `recent_cutoff` (= go-live + reset) now points to post-fix. This lets the kernel replay forward from now, capturing any fresh entry signals as they occur.

### 3. Backend Restart

`sudo systemctl restart forven-backend` — clears any stale registry state and forces a full `discover()`.

---

## Recommendations for Developer

### Short-term (already applied)
- Remove `reset()` from `register_strategy` flow.
- Consider making `get_active()` call `discover()` automatically if `_TYPE_MAP` is empty.

### Long-term
1. **Audit all `reset()` call sites** — `forven/api_core.py:10431` has the same pattern (`reset()` → `discover()`), though with a narrower window.
2. **Add a read-write lock** for `_TYPE_MAP` so the scanner never observes a partial state during agent tool registration.
3. **Improve kernel reconciliation** to allow backfilling past entries within `paper_kernel_backfill_bars` (currently 6) even when they're past the fresh window — a strategy that missed signals due to transient registry issues should be able to catch up.
4. **Add monitoring** for "no paper trades for N days" on paper-stage strategies so this kind of systemic starvation is surfaced within hours, not days.

### Strategies Affected

All 31 paper-stage strategies were affected. 22 had zero trades. The 9 that had some trades (S00986, S01057, S01922, S01556, S01781, S01803, S01665, S01735, S01627) were strategies that either entered paper before the first registry failure or got signals generated via legacy signal checkers (not the kernel path) during brief recovery windows.
