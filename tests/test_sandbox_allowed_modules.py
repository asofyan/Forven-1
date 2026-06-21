"""Tests for forven.sandbox.allowed_modules (P2-T03)."""
from __future__ import annotations

from forven.sandbox.allowed_modules import (
    ALLOWED_CHILD_MODULES,
    BLOCKED_BUILTINS,
    build_safe_globals,
    is_module_allowed,
)


def test_numpy_allowed():
    assert is_module_allowed("numpy") is True


def test_pandas_allowed():
    assert is_module_allowed("pandas") is True


def test_numpy_submodule_allowed():
    assert is_module_allowed("numpy.random") is True
    assert is_module_allowed("numpy.linalg.norm") is True


def test_os_blocked():
    assert is_module_allowed("os") is False


def test_subprocess_blocked():
    assert is_module_allowed("subprocess") is False


def test_socket_blocked():
    assert is_module_allowed("socket") is False


def test_empty_module_name_blocked():
    assert is_module_allowed("") is False


def test_lookalike_prefix_not_allowed():
    """`numpy_evil` must NOT be allowed just because `numpy` is."""
    assert is_module_allowed("numpy_evil") is False


def test_forven_market_data_view_allowed():
    assert is_module_allowed("forven.market_data_view") is True


def test_other_forven_modules_blocked():
    assert is_module_allowed("forven.brain") is False
    assert is_module_allowed("forven.db") is False


def test_safe_globals_strips_open():
    g = build_safe_globals()
    assert "__builtins__" in g
    assert g["__builtins__"].get("open") is None


def test_safe_globals_strips_all_blocked():
    g = build_safe_globals()
    builtins_dict = g["__builtins__"]
    for name in BLOCKED_BUILTINS:
        assert name not in builtins_dict, f"{name} should be stripped"


def test_safe_globals_keeps_safe_builtins():
    """Safe builtins like `len`, `range`, `print` must still be available."""
    g = build_safe_globals()
    builtins_dict = g["__builtins__"]
    assert "len" in builtins_dict
    assert "range" in builtins_dict
    assert "print" in builtins_dict
    assert "abs" in builtins_dict


def test_blocked_builtins_constant_is_frozen():
    assert isinstance(BLOCKED_BUILTINS, frozenset)


def test_allowed_modules_constant_is_frozen():
    assert isinstance(ALLOWED_CHILD_MODULES, frozenset)
