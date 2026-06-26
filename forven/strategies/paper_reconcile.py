"""Pure reconciliation between the execution kernel's view and recorded paper trades.

The live/paper scanner, each closed bar, runs the shared ``execution_kernel`` over a
strategy's history (via ``backtest.run_strategy_execution``) and gets a
:class:`~forven.strategies.execution_kernel.KernelResult` — the trades the backtest
WOULD have taken and the position it WOULD currently hold. This module turns that view
plus the strategy's already-recorded paper trades into a list of concrete actions
(open / close / backfill / refresh) for the scanner to apply.

Keeping this logic pure (no DB, no exchange) is what lets us prove, bar-by-bar, that
the resulting paper trades equal the backtest's trades — parity by construction — in a
fast unit test. The scanner layer only has to apply the actions via its existing
persistence/execution calls.

Matching is by ``(direction, entry_time)``: the kernel's ``entry_time`` is the bar's
open timestamp string (``str(df.index[idx])``), identical across runs over a growing
history prefix, so a recorded paper trade and its kernel counterpart line up exactly.
This is robust to missed scan cycles: any kernel-closed trade with no recorded
counterpart is backfilled, so a gap in scanner uptime never loses trades.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from forven.strategies.execution_kernel import KernelResult


ActionKind = Literal["open", "close", "backfill", "refresh"]


@dataclass
class ReconcileAction:
    kind: ActionKind
    direction: str
    entry_time: str
    # For open/refresh: the kernel's current open-position state (entry_price,
    # size_fraction, stop_price, target_price, trail_pct, entry_bar, regime, …).
    position: dict | None = None
    # For close/backfill: the kernel's finalized trade dict (exit_price, exit_time,
    # pnl_pct (net), exit_reason, …).
    trade: dict | None = None
    # For close/refresh: the recorded paper trade being acted on.
    recorded: dict | None = None


def _key(direction: str, entry_time: str) -> tuple[str, str]:
    return (str(direction or "long").strip().lower(), str(entry_time))


def reconcile(res: KernelResult, recorded: list[dict], *, recent_cutoff: str | None = None) -> list[ReconcileAction]:
    """Diff the kernel's view against recorded paper trades → ordered actions.

    ``recorded`` is the strategy's paper trades (open and closed), each a dict with at
    least ``direction``, ``entry_time`` and ``status`` ("open"/"closed"). The kernel
    ``res`` never force-closes, so ``res.closed_trades`` are real exits and
    ``res.open_positions`` is what should be live now.

    ``recent_cutoff`` (an ISO timestamp string, same format the kernel uses for
    ``entry_time``) bounds what gets RECORDED to "from go-live forward": kernel trades
    that ENTERED before it are treated as pre-tracking — their backfill is suppressed
    and such open positions are NOT adopted (they belong on the chart as triggers, not
    as actual trades). This is what stops a fresh/reset paper book from replaying the
    strategy's ENTIRE would-be history as trades. Closes/refreshes of ALREADY-recorded
    trades always proceed regardless of the cutoff. ``None`` (default) = full replay,
    which is the backtest-parity semantics the tests assert.

    Actions, in apply order:
      * ``close``    — a recorded OPEN trade the kernel has now finalized.
      * ``backfill`` — a kernel-finalized trade (entry ≥ cutoff) with no recorded
                       counterpart (opened & closed between scans) → record it closed.
      * ``open``     — a kernel OPEN position (entry ≥ cutoff) with no recorded
                       counterpart → open it.
      * ``refresh``  — a kernel OPEN position matching a recorded OPEN trade → update
                       its SL/TP/trailing for display.
    """
    def _recent(entry_time: str) -> bool:
        return recent_cutoff is None or str(entry_time) >= recent_cutoff

    recorded_by_key: dict[tuple[str, str], dict] = {}
    for r in recorded:
        recorded_by_key[_key(r.get("direction", "long"), r.get("entry_time"))] = r

    closes: list[ReconcileAction] = []
    backfills: list[ReconcileAction] = []
    # Closes & backfills, in the kernel's chronological (exit) order.
    for kc in res.closed_trades:
        if kc.get("open_at_end"):
            continue  # defensive; simulate() never emits these
        direction = str(kc.get("direction", "long")).strip().lower()
        entry_time = str(kc.get("entry_time"))
        k = _key(direction, entry_time)
        r = recorded_by_key.get(k)
        if r is None:
            if _recent(entry_time):  # only catch up RECENT missed trades, never the whole history
                backfills.append(ReconcileAction("backfill", direction, entry_time, trade=kc))
        elif str(r.get("status") or "open").strip().lower() != "closed":
            closes.append(ReconcileAction("close", direction, entry_time, trade=kc, recorded=r))
        # else: already recorded closed → nothing to do.

    opens: list[ReconcileAction] = []
    refreshes: list[ReconcileAction] = []
    for direction, pos in res.open_positions.items():
        direction = str(direction or "long").strip().lower()
        entry_time = str(pos.get("entry_time"))
        k = _key(direction, entry_time)
        r = recorded_by_key.get(k)
        if r is None or str(r.get("status") or "open").strip().lower() == "closed":
            if _recent(entry_time):  # don't adopt a position that opened before tracking began
                opens.append(ReconcileAction("open", direction, entry_time, position=pos))
        else:
            refreshes.append(ReconcileAction("refresh", direction, entry_time, position=pos, recorded=r))

    # Apply closes/backfills before opens so a same-direction re-entry after an exit is
    # never mistaken for a still-open position.
    return closes + backfills + opens + refreshes
