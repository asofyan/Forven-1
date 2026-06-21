"""Tests for GET /api/data/coverage endpoint."""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from forven.api_domains.data import get_coverage
from forven.data_manager import _save_stream_parquet


def _build_data_client() -> TestClient:
    """Build a TestClient that mounts the data router only."""
    from forven.routers.data import router as data_router
    app = FastAPI()
    app.include_router(data_router)
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return _build_data_client()


def _make_ohlcv(n: int = 5) -> pd.DataFrame:
    ts = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({
        "timestamp": ts,
        "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0,
    })


def _make_funding(n: int = 3) -> pd.DataFrame:
    ts = pd.date_range("2020-01-01", periods=n, freq="8h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "funding_rate": 0.0001})


def _make_oi(n: int = 3) -> pd.DataFrame:
    ts = pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame({"timestamp": ts, "open_interest": 1000.0})


def test_get_coverage_returns_ohlcv_rows(tmp_path):
    """Coverage endpoint returns row count and date range for OHLCV."""
    ohlcv_dir = tmp_path / "ohlcv" / "BTC-USDT"
    ohlcv_dir.mkdir(parents=True)
    _make_ohlcv(5).to_parquet(ohlcv_dir / "1h.parquet")

    with patch("forven.data.DATA_DIR", tmp_path / "ohlcv"):
        with patch("forven.data_manager.FUNDING_DIR", tmp_path / "funding"):
            with patch("forven.data_manager.OI_DIR", tmp_path / "oi"):
                result = get_coverage()

    assert "BTC-USDT" in result
    assert "ohlcv/1h" in result["BTC-USDT"]
    entry = result["BTC-USDT"]["ohlcv/1h"]
    assert entry["rows"] == 5
    assert "from" in entry
    assert "to" in entry


def test_get_coverage_includes_funding_and_oi(tmp_path):
    """Coverage endpoint includes funding and OI when parquet files exist."""
    ohlcv_dir = tmp_path / "ohlcv" / "ETH-USDT"
    ohlcv_dir.mkdir(parents=True)
    _make_ohlcv(5).to_parquet(ohlcv_dir / "1h.parquet")

    funding_path = tmp_path / "funding" / "ETH-USDT" / "history.parquet"
    _save_stream_parquet(_make_funding(3), funding_path, "funding", "ETH-USDT")

    oi_path = tmp_path / "oi" / "ETH-USDT" / "1h.parquet"
    _save_stream_parquet(_make_oi(3), oi_path, "oi", "ETH-USDT")

    with patch("forven.data.DATA_DIR", tmp_path / "ohlcv"):
        with patch("forven.data_manager.FUNDING_DIR", tmp_path / "funding"):
            with patch("forven.data_manager.OI_DIR", tmp_path / "oi"):
                result = get_coverage()

    assert "funding" in result["ETH-USDT"]
    assert result["ETH-USDT"]["funding"]["rows"] == 3
    assert "oi/1h" in result["ETH-USDT"]
    assert result["ETH-USDT"]["oi/1h"]["rows"] == 3


def test_get_coverage_omits_missing_streams(tmp_path):
    """Symbols with only OHLCV data don't include funding/oi keys."""
    ohlcv_dir = tmp_path / "ohlcv" / "SOL-USDT"
    ohlcv_dir.mkdir(parents=True)
    _make_ohlcv(5).to_parquet(ohlcv_dir / "1h.parquet")

    with patch("forven.data.DATA_DIR", tmp_path / "ohlcv"):
        with patch("forven.data_manager.FUNDING_DIR", tmp_path / "funding"):
            with patch("forven.data_manager.OI_DIR", tmp_path / "oi"):
                result = get_coverage()

    assert "SOL-USDT" in result
    assert "funding" not in result["SOL-USDT"]


# ---------------------------------------------------------------------------
# T23: /api/data/health per-stream freshness
# ---------------------------------------------------------------------------


def _reset_data_manager_stats():
    from forven.data_manager import _stats, _stats_lock
    with _stats_lock:
        _stats.clear()


def test_data_health_endpoint_returns_per_stream_freshness(client):
    _reset_data_manager_stats()
    resp = client.get("/api/data/health")
    assert resp.status_code == 200
    body = resp.json()
    assert "streams" in body
    # Each known stream either has stats or "never_ran"
    for s in ("funding", "oi", "ohlcv", "macro"):
        assert s in body["streams"]


def test_data_health_reflects_recent_collection(client, monkeypatch):
    from forven.data_manager import data_manager
    _reset_data_manager_stats()
    monkeypatch.setattr(data_manager, "get_active_symbols", lambda: set())
    data_manager.collect_funding()
    resp = client.get("/api/data/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["streams"]["funding"]["total_calls"] == 1
    assert body["streams"]["funding"]["last_success_ts"] is not None
    # Streams that never ran:
    assert body["streams"]["ohlcv"] == {"status": "never_ran"}


def test_data_health_preserves_legacy_shape(client):
    """T23 must not break the frontend's DataHealth contract.

    The frontend (frontend/src/lib/api/data.ts::getDataHealth) reads
    db_path/dataset_count/total_parquet_files etc. off this payload, so
    merging the new ``streams`` key must not displace the legacy body.
    """
    resp = client.get("/api/data/health")
    assert resp.status_code == 200
    body = resp.json()
    # New T22/T23 per-stream stats
    assert "streams" in body
    assert "generated_at" in body
    # Legacy fields the frontend still consumes
    for key in ("db_path", "dataset_count", "total_parquet_files"):
        assert key in body, f"missing legacy key: {key}"
