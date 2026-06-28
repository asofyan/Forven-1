"""Phase 3 regression tests for the paper+live engine audit (2026-06-28).

FREEZE-1: a hung position-managing scanner is now visible to the health monitor
  (RED when execution is active but the execution scan is stale).
FREEZE-3: an alive-but-FROZEN daemon (ticks hours old, process still alive) is now
  detected (RED) instead of reporting healthy.
"""
from datetime import datetime, timedelta, timezone

from forven.health_monitor import State, check_scanner_execution, check_daemon_liveness


def _iso_ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


# ─── FREEZE-1: scanner execution staleness ──────────────────────────────────────

def test_scanner_execution_idle_is_green(forven_db):
    from forven.db import kv_set
    kv_set("scanner_state", {"execution_allowed": False, "open_positions": 0,
                             "last_execution_scan": _iso_ago(100000)})
    assert check_scanner_execution().state == State.GREEN  # nothing to manage


def test_scanner_execution_stale_with_open_positions_is_red(forven_db):
    from forven.db import kv_set
    # Open positions exist but the execution scan hasn't run in 6h (> 5x the 1h default).
    kv_set("scanner_state", {"execution_allowed": True, "open_positions": 2,
                             "last_execution_scan": _iso_ago(6 * 3600)})
    status = check_scanner_execution()
    assert status.state == State.RED
    assert "not being managed" in status.message


def test_scanner_execution_fresh_is_green(forven_db):
    from forven.db import kv_set
    kv_set("scanner_state", {"execution_allowed": True, "open_positions": 1,
                             "last_execution_scan": _iso_ago(30)})
    assert check_scanner_execution().state == State.GREEN


# ─── FREEZE-3: alive-but-frozen daemon ──────────────────────────────────────────

def test_daemon_not_running_is_green(forven_db, monkeypatch):
    import forven.runtime_health as rh
    monkeypatch.setattr(rh, "normalize_daemon_state", lambda **k: {"running": False})
    assert check_daemon_liveness().state == State.GREEN


def test_daemon_alive_but_frozen_is_red(forven_db, monkeypatch):
    import forven.runtime_health as rh
    # Process alive, but its market tick is 5000s old (> the 600s default) -> FROZEN.
    monkeypatch.setattr(rh, "normalize_daemon_state",
                        lambda **k: {"running": True, "process_alive": True, "age_seconds": 5000.0})
    status = check_daemon_liveness()
    assert status.state == State.RED
    assert "FROZEN" in status.message


def test_daemon_alive_and_ticking_is_green(forven_db, monkeypatch):
    import forven.runtime_health as rh
    monkeypatch.setattr(rh, "normalize_daemon_state",
                        lambda **k: {"running": True, "process_alive": True, "age_seconds": 5.0})
    assert check_daemon_liveness().state == State.GREEN


def test_daemon_running_but_process_dead_is_red(forven_db, monkeypatch):
    import forven.runtime_health as rh
    monkeypatch.setattr(rh, "normalize_daemon_state",
                        lambda **k: {"running": True, "process_alive": False, "age_seconds": 1200.0})
    assert check_daemon_liveness().state == State.RED


# ─── RESTART-1: kernel replay window is not truncated by a short candle cache ────

def _ohlcv(n):
    import pandas as pd
    idx = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0}, index=idx
    )


def test_fetch_candles_refetches_when_cache_shorter_than_request(monkeypatch):
    """A 360-row cache must NOT satisfy a 1500-bar kernel request by returning the
    short tail (which truncates the replay and strands a long-held position)."""
    import forven.scanner as sc

    monkeypatch.setattr("forven.sim.clock.is_sim_active", lambda: False)
    monkeypatch.setattr(sc, "load_candle_snapshot", lambda coin, interval="1h": (_ohlcv(360), 0))
    monkeypatch.setattr(sc, "ohlcv_rows_to_dataframe", lambda rows: rows)
    monkeypatch.setattr(sc, "_scanner_bool_setting", lambda k, d=True: True)
    fetched = {"called": False}

    def _fmc(coin, bars, interval, clean):
        fetched["called"] = True
        assert bars >= 1500  # fetches the FULL requested window
        return _ohlcv(1500)

    monkeypatch.setattr(sc, "fetch_market_candles", _fmc)
    monkeypatch.setattr(sc, "publish_candle_snapshot", lambda *a, **k: None)
    monkeypatch.setattr(sc, "dataframe_to_ohlcv_rows", lambda df, max_rows=None: df)

    out = sc.fetch_candles("BTC", bars=1500, interval="1h")
    assert fetched["called"] is True
    assert len(out) == 1500


def test_fetch_candles_serves_cache_when_it_covers_request(monkeypatch):
    """When the cache already covers the request, serve it (no needless direct fetch)."""
    import forven.scanner as sc

    monkeypatch.setattr("forven.sim.clock.is_sim_active", lambda: False)
    monkeypatch.setattr(sc, "load_candle_snapshot", lambda coin, interval="1h": (_ohlcv(1500), 0))
    monkeypatch.setattr(sc, "ohlcv_rows_to_dataframe", lambda rows: rows)
    monkeypatch.setattr(sc, "_scanner_bool_setting", lambda k, d=True: True)

    def _fmc(*a, **k):
        raise AssertionError("must not direct-fetch when the cache covers the request")

    monkeypatch.setattr(sc, "fetch_market_candles", _fmc)
    out = sc.fetch_candles("BTC", bars=1500, interval="1h")
    assert len(out) == 1500
