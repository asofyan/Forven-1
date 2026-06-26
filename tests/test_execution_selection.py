"""Risk-engine (execution_profile) SELECTION + persistence.

Proves the backtest picks the best sizing/stop engine per strategy by a
risk-adjusted objective, and that the gauntlet freezes it onto the strategy so
paper/live adhere to it.
"""

from __future__ import annotations

import json

import pytest

from forven.strategies import execution_selection as sel


def test_candidate_profiles_cover_all_engines():
    grid = sel.candidate_profiles(max_risk=0.05)
    assert None in grid  # the shared default engine is always a candidate
    modes = {p["sizing_mode"] for p in grid if isinstance(p, dict)}
    assert modes == {"fraction", "atr", "kelly", "full"}
    # lean grid is a strict subset but still covers every engine
    lean = sel.candidate_profiles(max_risk=0.05, lean=True)
    assert None in lean
    assert {p["sizing_mode"] for p in lean if isinstance(p, dict)} == {"fraction", "atr", "kelly", "full"}
    assert len(lean) < len(grid)


def test_objective_score_prefers_requested_then_falls_back():
    m = {"sharpe_ratio": 1.2, "sortino_ratio": 1.8, "calmar_ratio": 0.9, "total_return": 0.4, "max_drawdown": 0.2}
    assert sel.objective_score(m, "sharpe_ratio") == 1.2
    assert sel.objective_score(m, "sortino") == 1.8
    assert sel.objective_score(m, "calmar") == 0.9
    # missing sharpe -> falls back to the next available risk-adjusted ratio
    assert sel.objective_score({"sortino_ratio": 2.0}, "sharpe_ratio") == 2.0
    # no ratios at all -> Calmar proxy (return / |dd|)
    assert sel.objective_score({"total_return": 0.5, "max_drawdown": 0.25}, "sharpe_ratio") == pytest.approx(2.0)


def _fake_backtest(metrics_by_mode_risk):
    """Return a backtest_strategy stand-in that maps execution_controls → metrics."""

    def _bt(strategy_id, asset, strategy_type, params, *, execution_controls=None, **kwargs):
        if execution_controls is None:
            key = "default"
        else:
            key = (execution_controls.get("sizing_mode"), execution_controls.get("risk_per_trade"))
        return {"metrics": metrics_by_mode_risk.get(key, {"sharpe_ratio": 0.0, "total_trades": 0, "max_drawdown": 0.1})}

    return _bt


def test_select_picks_best_risk_adjusted(monkeypatch):
    # atr@2% has the best Sharpe and passes guards → it must win over a higher-return
    # but huge-drawdown fraction profile and over the default.
    metrics = {
        "default": {"sharpe_ratio": 0.5, "total_trades": 40, "max_drawdown": 0.2, "total_return": 0.1},
        ("atr", 0.02): {"sharpe_ratio": 1.9, "total_trades": 35, "max_drawdown": 0.25, "total_return": 0.3},
        ("fraction", 0.05): {"sharpe_ratio": 0.8, "total_trades": 30, "max_drawdown": 0.92, "total_return": 0.9},
    }
    monkeypatch.setattr("forven.strategies.backtest.backtest_strategy", _fake_backtest(metrics))

    candidates = [None, {"sizing_mode": "atr", "risk_per_trade": 0.02, "atr_stop_multiplier": 2.0},
                  {"sizing_mode": "fraction", "risk_per_trade": 0.05, "stop_loss_pct": 3.0}]
    out = sel.select_execution_profile(
        strategy_id="S1", asset="BTC", strategy_type="rsi_momentum", params={}, timeframe="1h",
        candidates=candidates, objective="sharpe_ratio", max_dd=0.50, min_trades=10,
    )
    assert out["chosen"] == {"sizing_mode": "atr", "risk_per_trade": 0.02, "atr_stop_multiplier": 2.0}
    # the 0.92-drawdown fraction profile was guard-rejected despite higher return
    frac = next(s for s in out["scored"] if s["profile"] and s["profile"]["sizing_mode"] == "fraction")
    assert frac["eligible"] is False


def test_select_keeps_default_when_nothing_beats_it(monkeypatch):
    metrics = {
        "default": {"sharpe_ratio": 2.5, "total_trades": 50, "max_drawdown": 0.15, "total_return": 0.4},
        ("atr", 0.02): {"sharpe_ratio": 1.0, "total_trades": 35, "max_drawdown": 0.25, "total_return": 0.3},
    }
    monkeypatch.setattr("forven.strategies.backtest.backtest_strategy", _fake_backtest(metrics))
    out = sel.select_execution_profile(
        strategy_id="S1", asset="BTC", strategy_type="rsi_momentum", params={}, timeframe="1h",
        candidates=[None, {"sizing_mode": "atr", "risk_per_trade": 0.02, "atr_stop_multiplier": 2.0}],
        objective="sharpe_ratio",
    )
    assert out["chosen"] is None  # default engine wins → no profile imposed


# ── gauntlet persistence ────────────────────────────────────────────────────

def _insert_strategy(db_path, sid, params):
    from forven.db import get_db

    with get_db() as conn:
        conn.execute(
            "INSERT INTO strategies (id, name, type, symbol, timeframe, params, metrics, stage, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (sid, sid, "rsi_momentum", "BTC", "1h", json.dumps(params), "{}", "gauntlet", "active"),
        )


def test_gauntlet_persists_selected_profile(forven_db, monkeypatch):
    from forven.db import get_db
    from forven.gauntlet import tasks

    _insert_strategy(forven_db, "SEL1", {"rsi_period": 14})

    chosen = {"sizing_mode": "atr", "risk_per_trade": 0.02, "atr_stop_multiplier": 3.0}
    monkeypatch.setattr(tasks, "_execution_profile_selection_enabled", lambda: True)
    monkeypatch.setattr(
        "forven.strategies.execution_selection.select_execution_profile",
        lambda **kw: {"chosen": chosen, "chosen_label": "atr r2%", "chosen_score": 1.7,
                      "objective": "sharpe_ratio", "n_candidates": 12, "n_eligible": 5},
    )

    result = tasks._select_and_persist_execution_profile({"id": "wf1"}, "SEL1")
    assert result.get("skipped") is not True

    with get_db() as conn:
        row = dict(conn.execute("SELECT params, metrics FROM strategies WHERE id = ?", ("SEL1",)).fetchone())
    params = json.loads(row["params"])
    metrics = json.loads(row["metrics"])
    assert params["execution_profile"]["sizing_mode"] == "atr"
    assert params["execution_profile"]["risk_per_trade"] == 0.02
    assert metrics["gauntlet_selected_execution_profile"]["chosen_label"] == "atr r2%"


def test_gauntlet_skips_when_profile_already_present(forven_db, monkeypatch):
    from forven.gauntlet import tasks

    existing = {"sizing_mode": "kelly", "kelly_multiplier": 0.5}
    _insert_strategy(forven_db, "SEL2", {"rsi_period": 14, "execution_profile": existing})

    # If selection ran it would raise (proving idempotency means it must NOT run).
    monkeypatch.setattr(tasks, "_execution_profile_selection_enabled", lambda: True)
    monkeypatch.setattr(
        "forven.strategies.execution_selection.select_execution_profile",
        lambda **kw: (_ for _ in ()).throw(AssertionError("selection must not run when a profile exists")),
    )
    result = tasks._select_and_persist_execution_profile({"id": "wf1"}, "SEL2")
    assert result == {"skipped": True, "reason": "execution_profile already present"}
