"""Late "hop-in": when the kernel still HOLDS a position whose entry predates the recording
window (a still-active signal the scanner missed while the system was off), the paper path
should TAKE that position now — at the current price/time, re-anchoring the stop/target —
instead of leaving it as a chart-only trigger.

Covers all four touch points:
  * reconcile emits a `late_entry` open for a stale-but-held position (only when enabled);
  * the scanner opens at the CURRENT price with a re-anchored stop and the historical
    kernel_entry_time (so later scans REFRESH, not duplicate);
  * the close computes PnL from the recorded (late) entry, not the kernel's historical one;
  * a refresh does not clobber the re-anchored stop with the kernel's historical level.
"""

from __future__ import annotations

import json

import pytest

import forven.scanner as sc
from forven.db import get_db
from forven.strategies.execution_kernel import KernelResult
from forven.strategies.paper_reconcile import ReconcileAction, reconcile

CUTOFF = "2026-06-26 16:00:00+00:00"
WINDOW = "2026-05-01 00:00:00+00:00"
STALE_ENTRY = "2026-06-01 04:00:00+00:00"   # ~25 days before the cutoff
STRAT = {"asset": "ETH", "params": {"execution_profile": {"risk_per_trade": 0.01}}}


def _kr(open_pos=None, closed=None):
    return KernelResult(closed_trades=closed or [], open_positions=open_pos or {}, closed_gross=[])


def _stale_short_pos():
    return {"entry_time": STALE_ENTRY, "entry_price": 2400.0, "size_fraction": 0.5,
            "stop_price": 2450.0, "entry_bar": 10, "regime": "trend"}


# stop distance preserved as a fraction of entry: (2450-2400)/2400 = 2.0833%
def _expected_short_stop(cur):
    return cur * (1.0 + (2450.0 - 2400.0) / 2400.0)


# ── reconcile ────────────────────────────────────────────────────────────────────────

def test_stale_open_suppressed_when_late_entry_disabled():
    acts = reconcile(_kr(open_pos={"short": _stale_short_pos()}), [], recent_cutoff=CUTOFF, window_start=WINDOW)
    assert [a for a in acts if a.kind == "open"] == []  # default: stale entry is NOT opened


def test_stale_open_emits_late_entry_when_enabled():
    acts = reconcile(_kr(open_pos={"short": _stale_short_pos()}), [],
                     recent_cutoff=CUTOFF, window_start=WINDOW, late_entry=True)
    opens = [a for a in acts if a.kind == "open"]
    assert len(opens) == 1
    assert opens[0].late_entry is True
    assert opens[0].direction == "short"
    assert opens[0].entry_time == STALE_ENTRY  # historical, so the next scan refreshes it


def test_recent_open_is_never_late_even_when_enabled():
    pos = dict(_stale_short_pos(), entry_time="2026-06-27 08:00:00+00:00")  # within the window
    acts = reconcile(_kr(open_pos={"short": pos}), [], recent_cutoff=CUTOFF, window_start=WINDOW, late_entry=True)
    opens = [a for a in acts if a.kind == "open"]
    assert len(opens) == 1 and opens[0].late_entry is False  # recent → faithful kernel open


# ── scanner open (hop in at current price) ─────────────────────────────────────────────

def _open_late(forven_db, current_price=1590.0, current_time="2026-06-27 12:00:00+00:00"):
    action = ReconcileAction("open", "short", STALE_ENTRY, position=_stale_short_pos(), late_entry=True)
    msg = sc._kernel_open_paper_trade("S-LATE", STRAT, action, sizing_equity=10000.0, leverage=1.0,
                                      current_price=current_price, current_time=current_time)
    assert msg and "late hop-in" in msg  # the applier returns a log message, not the id
    with get_db() as c:
        row = dict(c.execute(
            "SELECT * FROM trades WHERE COALESCE(strategy_id, strategy)='S-LATE' AND status='OPEN' "
            "ORDER BY rowid DESC LIMIT 1").fetchone())
    return row["id"], row


def test_late_entry_opens_at_current_price_with_reanchored_stop(forven_db):
    tid, row = _open_late(forven_db)
    sd = json.loads(row["signal_data"])
    assert row["entry_price"] == pytest.approx(1590.0)                 # CURRENT price, not 2400
    assert row["opened_at"] == "2026-06-27T12:00:00+00:00"            # current time
    assert sd["late_entry"] is True
    assert sd["kernel_entry_time"] == STALE_ENTRY                     # historical → reconcile key
    assert sd["stop_loss_price"] == pytest.approx(_expected_short_stop(1590.0), rel=1e-4)
    assert sd["stop_loss_price"] < 1700.0                             # re-anchored near 1623, not 2450


def test_late_entry_close_uses_recorded_entry_not_kernel_pnl(forven_db):
    tid, row = _open_late(forven_db)
    # The kernel's historical short (from 2400) would show a huge +30% at exit 1500; our late
    # short entered at 1590, so its real PnL is only (1590-1500)/1590 ≈ +5.66%.
    kernel_trade = {"exit_price": 1500.0, "pnl_pct": 0.30, "exit_reason": "signal",
                    "exit_time": "2026-06-27 16:00:00+00:00"}
    sc._kernel_close_recorded("S-LATE", STRAT, row, kernel_trade, "short")
    with get_db() as c:
        out = dict(c.execute("SELECT status, pnl_pct, closed_at FROM trades WHERE id=?", (tid,)).fetchone())
    assert out["status"] == "CLOSED"
    assert out["closed_at"] == "2026-06-27T16:00:00+00:00"           # kernel exit-bar time
    assert out["pnl_pct"] == pytest.approx((1590.0 - 1500.0) / 1590.0, rel=0.02)  # from OUR entry
    assert out["pnl_pct"] < 0.10                                      # NOT the kernel's 0.30


def test_refresh_does_not_clobber_late_entry_reanchored_stop(forven_db):
    tid, row = _open_late(forven_db)
    # The kernel pos still carries the HISTORICAL stop (2450); a refresh must leave the
    # re-anchored ~1623 in place.
    kpos = {"entry_time": STALE_ENTRY, "entry_price": 2400.0, "stop_price": 2450.0, "target_price": None}
    sc._kernel_refresh_paper_trade(
        ReconcileAction("refresh", "short", STALE_ENTRY, position=kpos, recorded={"_row": row})
    )
    with get_db() as c:
        sd = json.loads(dict(c.execute("SELECT signal_data FROM trades WHERE id=?", (tid,)).fetchone())["signal_data"])
    assert sd["stop_loss_price"] == pytest.approx(_expected_short_stop(1590.0), rel=1e-4)  # unchanged
