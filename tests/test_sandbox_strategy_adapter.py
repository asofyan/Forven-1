"""Tests for forven.sandbox.strategy_adapter (P2-T08).

Coverage:
- ``is_custom_strategy_path`` matches the legacy/modern roots, both forward
  and backslash, case-insensitive; rejects builtin paths.
- ``get_sandbox_config`` returns safe defaults when settings are missing
  and operator-supplied values when present.
- ``load_sandboxed`` returns None when disabled, when path doesn't exist,
  and when path is a built-in; returns a SandboxedStrategy otherwise.
- ``SandboxedStrategy.evaluate`` happy-path returns the runner's payload.
- ``SandboxedStrategy.evaluate`` AST-blocked path returns the
  ``{"trades": [], "stats": {}, "error": "sandbox_block:ast_block"}`` shape.
- ``SandboxedStrategy.evaluate`` timeout path returns ``error: sandbox_timeout``.
"""
from __future__ import annotations

import tempfile
import textwrap
from pathlib import Path

import pytest

from forven import db as forven_db
from forven.sandbox import strategy_adapter as adapter
from forven.sandbox.strategy_adapter import (
    SandboxedStrategy,
    get_sandbox_config,
    is_custom_strategy_path,
    load_sandboxed,
)


# ---------- fixtures -------------------------------------------------------


@pytest.fixture
def fresh_db(monkeypatch):
    """Re-route FORVEN_HOME so sandbox_runs writes go to a tmpdir DB."""
    with tempfile.TemporaryDirectory() as td:
        monkeypatch.setenv("FORVEN_HOME", td)
        if hasattr(forven_db, "_DB_PATH"):
            forven_db._DB_PATH = None  # type: ignore[attr-defined]
        if hasattr(forven_db, "_init_db_done"):
            forven_db._init_db_done = False  # type: ignore[attr-defined]
        forven_db.init_db()
        yield td


def _write_strategy(tmp_path: Path, code: str, name: str = "strat.py") -> Path:
    p = tmp_path / name
    p.write_text(code, encoding="utf-8")
    return p


# ---------- is_custom_strategy_path ----------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "C:/Users/x/juddex/strategies/custom/strat.py",
        "C:\\Users\\x\\juddex\\strategies\\custom\\strat.py",
        "/home/u/juddex/strategies/custom/foo.py",
        "C:/Users/x/forven/strategies/custom/strat.py",
        "C:\\Users\\x\\forven\\strategies\\custom\\strat.py",
        "C:/Users/x/JUDDEX/Strategies/Custom/strat.py",  # case-insensitive
    ],
)
def test_custom_paths_match(path: str):
    assert is_custom_strategy_path(path) is True


@pytest.mark.parametrize(
    "path",
    [
        "C:/Users/x/forven/strategies/builtin/rsi.py",
        "/home/u/forven/strategies/builtin/macd.py",
        "C:/some/other/place/strat.py",
        "/tmp/strat.py",
    ],
)
def test_non_custom_paths_reject(path: str):
    assert is_custom_strategy_path(path) is False


def test_is_custom_strategy_path_accepts_pathlib():
    p = Path("forven/strategies/custom/foo.py")
    assert is_custom_strategy_path(p) is True


# ---------- get_sandbox_config ---------------------------------------------


def test_get_sandbox_config_defaults_when_settings_missing(monkeypatch):
    """If get_settings throws, we still get a usable defaults dict."""
    def _boom():
        raise RuntimeError("settings gone")

    monkeypatch.setattr("forven.api_core.get_settings", _boom)
    cfg = get_sandbox_config()
    assert cfg == {
        "enabled": False,
        "mem_mb": 256,
        "cpu_s": 30,
        "wall_s": 60,
    }


def test_get_sandbox_config_defaults_when_settings_not_dict(monkeypatch):
    monkeypatch.setattr("forven.api_core.get_settings", lambda: "not a dict")
    cfg = get_sandbox_config()
    assert cfg["enabled"] is False
    assert cfg["mem_mb"] == 256


def test_get_sandbox_config_reads_operator_values(monkeypatch):
    monkeypatch.setattr(
        "forven.api_core.get_settings",
        lambda: {
            "sandbox_enabled": True,
            "sandbox_mem_mb": 512,
            "sandbox_cpu_s": 120,
            "sandbox_wall_s": 300,
            # other unrelated keys must not interfere
            "backtest_duration_days": 30,
        },
    )
    cfg = get_sandbox_config()
    assert cfg == {
        "enabled": True,
        "mem_mb": 512,
        "cpu_s": 120,
        "wall_s": 300,
    }


def test_get_sandbox_config_falls_back_per_key_when_partial(monkeypatch):
    """Missing keys still fall back to defaults — no KeyError."""
    monkeypatch.setattr(
        "forven.api_core.get_settings",
        lambda: {"sandbox_enabled": True},
    )
    cfg = get_sandbox_config()
    assert cfg["enabled"] is True
    assert cfg["mem_mb"] == 256
    assert cfg["cpu_s"] == 30
    assert cfg["wall_s"] == 60


# ---------- load_sandboxed -------------------------------------------------


def test_load_sandboxed_returns_none_when_disabled(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        adapter,
        "get_sandbox_config",
        lambda: {"enabled": False, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    custom = tmp_path / "juddex" / "strategies" / "custom"
    custom.mkdir(parents=True)
    f = custom / "s.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert load_sandboxed(f) is None


def test_load_sandboxed_returns_none_for_missing_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        adapter,
        "get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    missing = tmp_path / "juddex" / "strategies" / "custom" / "missing.py"
    assert load_sandboxed(missing) is None


def test_load_sandboxed_returns_none_for_builtin_path(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        adapter,
        "get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 256, "cpu_s": 30, "wall_s": 60},
    )
    builtin = tmp_path / "forven" / "strategies" / "builtin"
    builtin.mkdir(parents=True)
    f = builtin / "rsi.py"
    f.write_text("x = 1\n", encoding="utf-8")
    assert load_sandboxed(f) is None


def test_load_sandboxed_returns_adapter_when_eligible(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        adapter,
        "get_sandbox_config",
        lambda: {"enabled": True, "mem_mb": 384, "cpu_s": 45, "wall_s": 90},
    )
    custom = tmp_path / "juddex" / "strategies" / "custom"
    custom.mkdir(parents=True)
    f = custom / "s.py"
    f.write_text("x = 1\n", encoding="utf-8")
    s = load_sandboxed(f, strategy_id="S00001")
    assert isinstance(s, SandboxedStrategy)
    assert s.strategy_id == "S00001"
    assert s.mem_mb == 384
    assert s.cpu_s == 45
    assert s.wall_s == 90
    assert s.strategy_path == f


# ---------- SandboxedStrategy.evaluate -------------------------------------


HELLO_STRATEGY = textwrap.dedent(
    """
    def generate_signal(ohlcv):
        return {"trades": [{"action": "buy"}], "stats": {"hello": "world"}}
    """
).strip()

AST_BLOCKED_STRATEGY = textwrap.dedent(
    """
    import os
    def generate_signal(ohlcv):
        return {"trades": [], "stats": {}}
    """
).strip()

INFINITE_LOOP_STRATEGY = textwrap.dedent(
    """
    def generate_signal(ohlcv):
        while True:
            pass
    """
).strip()


def test_evaluate_happy_path_returns_payload(fresh_db, tmp_path: Path):
    f = _write_strategy(tmp_path, HELLO_STRATEGY)
    s = SandboxedStrategy(f, wall_s=15)
    out = s.evaluate({"bars": []})
    assert isinstance(out, dict)
    assert out.get("stats", {}).get("hello") == "world"
    assert "error" not in out


def test_evaluate_ast_blocked_returns_error_dict(fresh_db, tmp_path: Path):
    f = _write_strategy(tmp_path, AST_BLOCKED_STRATEGY)
    s = SandboxedStrategy(f, wall_s=15)
    out = s.evaluate({})
    assert out["trades"] == []
    assert out["stats"] == {}
    assert out["error"].startswith("sandbox_block:")


def test_evaluate_timeout_returns_error_dict(fresh_db, tmp_path: Path):
    f = _write_strategy(tmp_path, INFINITE_LOOP_STRATEGY)
    s = SandboxedStrategy(f, wall_s=1)  # 1 sec wall timeout
    out = s.evaluate({})
    assert out["trades"] == []
    assert out["error"] == "sandbox_timeout"


def test_evaluate_never_returns_none(fresh_db, tmp_path: Path):
    """Per the adapter contract, evaluate must always return a dict."""
    # Missing file → runner returns AST-block error → adapter returns dict
    s = SandboxedStrategy(tmp_path / "does_not_exist.py", wall_s=5)
    out = s.evaluate({})
    assert out is not None
    assert isinstance(out, dict)
    assert "error" in out


def test_evaluate_passes_strategy_id_to_runner(fresh_db, tmp_path: Path):
    f = _write_strategy(tmp_path, HELLO_STRATEGY)
    s = SandboxedStrategy(f, strategy_id="S12345", wall_s=15)
    s.evaluate({})
    with forven_db.get_db() as conn:
        rows = [dict(r) for r in conn.execute("SELECT * FROM sandbox_runs ORDER BY id")]
    assert rows
    assert rows[-1]["strategy_id"] == "S12345"
