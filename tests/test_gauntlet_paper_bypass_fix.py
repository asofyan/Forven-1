"""2026-06-15 gauntlet->paper bypass hardening.

Root cause (audit): 6/8 paper strategies reached `paper` without the gauntlet
workflow running — promoted (force=false) via the artifact-based gate under a
relaxed/narrowed config. Fixes verified here:

  (F1 workflow-binding was DROPPED — it broke the intended gate-based graduation,
   run_testing_step / actor=system. The gate hardening below is the fix instead.)
  F2  policy._evaluate_gauntlet_gate: immutable floors (_PAPER_GATE_FLOORS) make
      the paper gate un-relaxable below the design defaults.
  F4b policy._evaluate_gauntlet_gate: WFA fold-rate + param-jitter safety floors
      fire whenever the test RAN, regardless of required_tests membership.
"""

import copy
import json
from datetime import datetime, timedelta, timezone

import forven.policy as policy
from forven.db import get_db
from forven.policy import (
    DEFAULT_PIPELINE_CONFIG,
    _PAPER_GATE_FLOORS,
    _evaluate_gauntlet_gate,
    load_pipeline_config,
    save_pipeline_config,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

_PASS_METRICS = {
    "robustness_score": 80,
    "total_trades": 60,
    "out_of_sample": {
        "sharpe": 1.0,
        "profit_factor": 1.3,
        "win_rate": 55.0,
        "total_return_pct": 12.0,
        "max_drawdown_pct": 0.10,
    },
}


def _insert_gauntlet(conn, sid, metrics):
    conn.execute(
        "INSERT INTO strategies (id, name, type, status, stage, owner, display_id, "
        "stage_changed_at, metrics, created_at) VALUES (?, ?, 'rsi_momentum', ?, ?, 'brain', ?, ?, ?, ?)",
        (
            sid, sid, "gauntlet", "gauntlet", sid,
            (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
            json.dumps(metrics),
            (datetime.now(timezone.utc) - timedelta(days=20)).isoformat(),
        ),
    )
    conn.commit()


def _stub_prereqs(monkeypatch, payloads):
    monkeypatch.setattr(policy, "_load_gauntlet_artifact_counts", lambda sid: {"optimization": 1, "walk_forward": 1})
    monkeypatch.setattr(policy, "_check_artifact_ordering", lambda sid, req=None: (True, "ok"))
    monkeypatch.setattr(policy, "_check_validation_freshness", lambda sid, req=None: (True, "ok"))
    monkeypatch.setattr(policy, "_extract_gauntlet_verdict_payloads", lambda sid, row, metrics: (payloads, "pass"))
    monkeypatch.setattr(
        policy, "_load_pipeline_settings",
        lambda: {"gate_multi_tf_sweep_enabled": False, "gate_require_artifact_rows_enabled": False},
    )


def _cfg(**gauntlet_overrides):
    cfg = copy.deepcopy(DEFAULT_PIPELINE_CONFIG)
    cfg["gauntlet"].update(gauntlet_overrides)
    return cfg


# ---------------------------------------------------------------------------
# F2 — floors hold even when the config is relaxed
# ---------------------------------------------------------------------------

def test_f2_robustness_floor_holds_under_relaxed_config(forven_db, monkeypatch):
    _stub_prereqs(monkeypatch, {})
    cfg = _cfg(required_tests=[], min_robustness_score=0)  # operator tries to relax to 0
    metrics = copy.deepcopy(_PASS_METRICS)
    metrics["robustness_score"] = 10
    with get_db() as conn:
        _insert_gauntlet(conn, "f2-rob", metrics)
    passed, msg = _evaluate_gauntlet_gate("f2-rob", cfg)
    assert not passed, msg
    assert "robustness too low" in msg.lower()
    assert "50" in msg  # floored at the design default


def test_f2_mc_dd_ceiling_holds_under_relaxed_config(forven_db, monkeypatch):
    _stub_prereqs(monkeypatch, {"monte_carlo": {"max_dd_p95": 0.50, "n_trades": 60}})
    cfg = _cfg(required_tests=[], mc_max_dd_p95=0.99)  # operator tries to relax DD limit to 99%
    with get_db() as conn:
        _insert_gauntlet(conn, "f2-mc", _PASS_METRICS)
    passed, msg = _evaluate_gauntlet_gate("f2-mc", cfg)
    assert not passed, msg
    assert "95th percentile DD" in msg
    assert "40%" in msg  # capped at the 0.40 floor, not 99%


# ---------------------------------------------------------------------------
# Trade-count floor — capital gate must reject thin samples even with NO Monte
# Carlo artifact (the bypass that put 5-trade strategies on paper)
# ---------------------------------------------------------------------------

def test_trade_count_floor_blocks_thin_sample_without_mc(forven_db, monkeypatch):
    _stub_prereqs(monkeypatch, {})  # no MC / WFA / jitter artifacts at all
    cfg = _cfg(required_tests=[], min_trades=1)  # operator tries to relax min_trades to 1
    metrics = copy.deepcopy(_PASS_METRICS)
    metrics["total_trades"] = 5  # top-level mirrors OOS leg
    metrics["in_sample"] = {"total_trades": 7}
    metrics["out_of_sample"] = {**metrics["out_of_sample"], "total_trades": 5}  # IS+OOS = 12
    with get_db() as conn:
        _insert_gauntlet(conn, "thin-trades", metrics)
    passed, msg = _evaluate_gauntlet_gate("thin-trades", cfg)
    assert not passed, msg
    assert "trades" in msg.lower()
    assert str(_PAPER_GATE_FLOORS["min_trades"]) in msg  # floored at design default, not the relaxed 1


def test_trade_count_floor_passes_thick_sample_without_mc(forven_db, monkeypatch):
    # A healthy trade count clears ->paper even with no MC artifact (no false reject).
    _stub_prereqs(monkeypatch, {})
    cfg = _cfg(required_tests=[])
    metrics = copy.deepcopy(_PASS_METRICS)  # total_trades = 60
    with get_db() as conn:
        _insert_gauntlet(conn, "thick-trades", metrics)
    passed, msg = _evaluate_gauntlet_gate("thick-trades", cfg)
    assert passed, msg


# ---------------------------------------------------------------------------
# F4(b) — safety floors fire whenever the test ran, even if not in required_tests
# ---------------------------------------------------------------------------

def test_f4_wfa_fold_floor_fires_when_not_required(forven_db, monkeypatch):
    _stub_prereqs(monkeypatch, {"walk_forward": {"folds": 3, "pass_rate": 0.2}})
    cfg = _cfg(required_tests=["cost_stress"])  # walk_forward narrowed OUT of required
    cfg.setdefault("robustness_thresholds", {})["wfa_fold_pass_rate_min"] = 0.0  # and relaxed to 0
    with get_db() as conn:
        _insert_gauntlet(conn, "f4-wfa", _PASS_METRICS)
    passed, msg = _evaluate_gauntlet_gate("f4-wfa", cfg)
    assert not passed, msg
    assert "Walk-forward pass rate" in msg


def test_f4_jitter_floor_fires_when_not_required(forven_db, monkeypatch):
    _stub_prereqs(monkeypatch, {"param_jitter": {"pass_rate": 0.3}})
    cfg = _cfg(required_tests=["cost_stress"])  # param_jitter narrowed OUT of required
    cfg.setdefault("robustness_thresholds", {})["param_jitter_pass_rate_min"] = 0.0
    with get_db() as conn:
        _insert_gauntlet(conn, "f4-jit", _PASS_METRICS)
    passed, msg = _evaluate_gauntlet_gate("f4-jit", cfg)
    assert not passed, msg
    assert "Parameter jitter pass rate" in msg


# ---------------------------------------------------------------------------
# Positive control — a genuinely passing strategy still clears the floored gate
# ---------------------------------------------------------------------------

def test_floored_gate_still_passes_legit_strategy(forven_db, monkeypatch):
    _stub_prereqs(monkeypatch, {
        "walk_forward": {"folds": 4, "pass_rate": 1.0},
        "param_jitter": {"pass_rate": 0.9},
        "monte_carlo": {"max_dd_p95": 0.20, "n_trades": 60},
    })
    cfg = _cfg(required_tests=[])
    with get_db() as conn:
        _insert_gauntlet(conn, "ok-strat", _PASS_METRICS)
    passed, msg = _evaluate_gauntlet_gate("ok-strat", cfg)
    assert passed, msg


# ---------------------------------------------------------------------------
# F3 — hidden sub-thresholds are wired through Settings (percent-normalized)
# ---------------------------------------------------------------------------

def test_f3_mc_dd_setting_percent_normalized_and_wired(forven_db, monkeypatch):
    # Operator tightens MC p95 DD to 35% via the real settings write path (percent input).
    save_pipeline_config({"gauntlet": {"mc_max_dd_p95": 35}})
    cfg = load_pipeline_config()
    assert abs(float(cfg["gauntlet"]["mc_max_dd_p95"]) - 0.35) < 1e-9  # normalized to fraction
    _stub_prereqs(monkeypatch, {"monte_carlo": {"max_dd_p95": 0.38, "n_trades": 60}})
    cfg["gauntlet"]["required_tests"] = []
    with get_db() as conn:
        _insert_gauntlet(conn, "f3-mc", _PASS_METRICS)
    passed, msg = _evaluate_gauntlet_gate("f3-mc", cfg)
    assert not passed, msg  # 38% exceeds the tightened 35% ceiling
    assert "95th percentile DD" in msg
