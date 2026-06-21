"""Tests for Bot Factory — DB, circuit breaker, sandbox, engine, templates, API."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest


# ── DB CRUD Tests ───────────────────────────────────────────────────


class TestBotCRUD:
    def test_create_and_get_bot(self, forven_db):
        from forven.db import create_bot, get_bot

        bot_id = create_bot({"name": "Test Bot", "model": "gpt-4.1-mini", "soul": "You are helpful."})
        assert bot_id

        bot = get_bot(bot_id)
        assert bot is not None
        assert bot["name"] == "Test Bot"
        assert bot["model"] == "gpt-4.1-mini"
        assert bot["soul"] == "You are helpful."
        assert bot["status"] == "stopped"
        assert bot["capital_allocation"] == 100000

    def test_list_bots(self, forven_db):
        from forven.db import create_bot, list_bots

        create_bot({"name": "Bot A", "model": "gpt-4.1-mini"})
        create_bot({"name": "Bot B", "model": "gpt-4.1"})

        bots = list_bots()
        assert len(bots) == 2
        names = {b["name"] for b in bots}
        assert names == {"Bot A", "Bot B"}

    def test_update_bot_creates_version(self, forven_db):
        from forven.db import create_bot, update_bot, get_bot, get_bot_config_versions

        bot_id = create_bot({"name": "Original", "model": "gpt-4.1-mini"})
        update_bot(bot_id, {"name": "Updated"})

        bot = get_bot(bot_id)
        assert bot["name"] == "Updated"

        versions = get_bot_config_versions(bot_id)
        assert len(versions) == 1
        assert versions[0]["version"] == 1

    def test_delete_bot(self, forven_db):
        from forven.db import create_bot, delete_bot, get_bot

        bot_id = create_bot({"name": "Doomed", "model": "gpt-4.1-mini"})
        delete_bot(bot_id)
        assert get_bot(bot_id) is None

    def test_delete_running_bot_raises(self, forven_db):
        from forven.db import create_bot, delete_bot, set_bot_status

        bot_id = create_bot({"name": "Running", "model": "gpt-4.1-mini"})
        set_bot_status(bot_id, "running", pid=12345)

        with pytest.raises(ValueError, match="running"):
            delete_bot(bot_id)

    def test_clone_bot(self, forven_db):
        from forven.db import create_bot, clone_bot, get_bot

        bot_id = create_bot({
            "name": "Original",
            "model": "gpt-4.1-mini",
            "soul": "Test soul",
            "capital_allocation": 50000,
        })
        cloned_id = clone_bot(bot_id, "Clone")

        assert cloned_id != bot_id
        cloned = get_bot(cloned_id)
        assert cloned["name"] == "Clone"
        assert cloned["soul"] == "Test soul"
        assert cloned["capital_allocation"] == 50000

    def test_json_fields_round_trip(self, forven_db):
        from forven.db import create_bot, get_bot

        bot_id = create_bot({
            "name": "JSON Bot",
            "model": "gpt-4.1-mini",
            "locked_pairs": ["BTC/USDT", "ETH/USDT"],
            "web_allowlist": ["reuters.com", "coindesk.com"],
            "session_hours": {"start": "09:30", "end": "16:00", "timezone": "America/New_York"},
        })
        bot = get_bot(bot_id)
        assert bot["locked_pairs"] == ["BTC/USDT", "ETH/USDT"]
        assert bot["web_allowlist"] == ["reuters.com", "coindesk.com"]
        assert bot["session_hours"]["start"] == "09:30"


# ── Bot Status Tests ────────────────────────────────────────────────


class TestBotStatus:
    def test_set_and_get_status(self, forven_db):
        from forven.db import create_bot, set_bot_status, get_bot_status

        bot_id = create_bot({"name": "Status Bot", "model": "gpt-4.1-mini"})
        set_bot_status(bot_id, "running", pid=12345)

        status = get_bot_status(bot_id)
        assert status["status"] == "running"
        assert status["pid"] == 12345
        assert status["consecutive_errors"] == 0

    def test_heartbeat(self, forven_db):
        from forven.db import create_bot, heartbeat_bot, get_bot_status

        bot_id = create_bot({"name": "HB Bot", "model": "gpt-4.1-mini"})
        heartbeat_bot(bot_id)

        status = get_bot_status(bot_id)
        assert status["last_heartbeat"] is not None

    def test_increment_errors(self, forven_db):
        from forven.db import create_bot, increment_bot_errors

        bot_id = create_bot({"name": "Error Bot", "model": "gpt-4.1-mini"})

        count1 = increment_bot_errors(bot_id)
        assert count1 == 1

        count2 = increment_bot_errors(bot_id)
        assert count2 == 2

    def test_reset_errors(self, forven_db):
        from forven.db import create_bot, increment_bot_errors, reset_bot_errors, get_bot_status

        bot_id = create_bot({"name": "Reset Bot", "model": "gpt-4.1-mini"})
        increment_bot_errors(bot_id)
        increment_bot_errors(bot_id)
        reset_bot_errors(bot_id)

        status = get_bot_status(bot_id)
        assert status["consecutive_errors"] == 0

    def test_increment_llm_calls(self, forven_db):
        from forven.db import create_bot, increment_bot_llm_calls

        bot_id = create_bot({"name": "LLM Bot", "model": "gpt-4.1-mini"})

        count = increment_bot_llm_calls(bot_id)
        assert count == 1

        count2 = increment_bot_llm_calls(bot_id)
        assert count2 == 2

    def test_get_running_bots(self, forven_db):
        from forven.db import create_bot, set_bot_status, get_running_bots

        bot_a = create_bot({"name": "A", "model": "gpt-4.1-mini"})
        create_bot({"name": "B", "model": "gpt-4.1-mini"})
        set_bot_status(bot_a, "running", pid=111)

        running = get_running_bots()
        assert len(running) == 1
        assert running[0]["bot_id"] == bot_a


# ── Decision Log Tests ──────────────────────────────────────────────


class TestDecisionLog:
    def test_log_and_retrieve(self, forven_db):
        from forven.db import create_bot, log_bot_decision, get_bot_decisions

        bot_id = create_bot({"name": "Log Bot", "model": "gpt-4.1-mini"})
        log_bot_decision(
            bot_id=bot_id,
            event_trigger={"type": "price_update", "ticker": "BTC/USDT"},
            reasoning="BTC looks bullish",
            action_type="trade",
            action_data={"action": "BUY", "ticker": "BTC/USDT", "qty": 1},
            verbosity="standard",
        )

        decisions = get_bot_decisions(bot_id)
        assert len(decisions) == 1
        assert decisions[0]["action_type"] == "trade"
        assert decisions[0]["reasoning"] == "BTC looks bullish"
        assert decisions[0]["action_data"]["ticker"] == "BTC/USDT"


# ── Trade Execution Tests ───────────────────────────────────────────


class TestBotTradeExecution:
    def test_execute_bot_trade(self, forven_db):
        from forven.db import create_bot, execute_bot_trade, get_recent_trades

        bot_id = create_bot({"name": "Trader Bot", "model": "gpt-4.1-mini"})
        trade_id = execute_bot_trade(
            bot_id=bot_id,
            ticker="BTC/USDT",
            direction="long",
            qty=1,
            price=50000.0,
            reasoning="Looks bullish",
        )

        assert trade_id.startswith("E")
        trades = get_recent_trades(limit=10)
        bot_trades = [t for t in trades if t.get("source") == f"bot:{bot_id}"]
        assert len(bot_trades) == 1
        assert bot_trades[0]["asset"] == "BTC/USDT"
        assert bot_trades[0]["direction"] == "long"


# ── Template Tests ──────────────────────────────────────────────────


class TestTemplates:
    def test_create_and_list_templates(self, forven_db):
        from forven.db import create_bot_template, list_bot_templates

        tid = create_bot_template("Test Template", "A test", {"soul": "Helpful"})
        assert tid

        templates = list_bot_templates()
        assert len(templates) == 1
        assert templates[0]["name"] == "Test Template"
        assert templates[0]["config_snapshot"]["soul"] == "Helpful"

    def test_delete_builtin_template_raises(self, forven_db):
        from forven.db import create_bot_template, delete_bot_template

        tid = create_bot_template("Builtin", "Built-in template", {"soul": "x"}, is_builtin=True)

        with pytest.raises(ValueError, match="built-in"):
            delete_bot_template(tid)

    def test_seed_builtin_templates(self, forven_db):
        from forven.bot_factory.templates import seed_builtin_templates
        from forven.db import list_bot_templates

        count = seed_builtin_templates()
        assert count == 4

        templates = list_bot_templates()
        assert len(templates) == 4
        names = {t["name"] for t in templates}
        assert "Momentum Scalper" in names
        assert "Conservative Swing Trader" in names

        # Idempotent
        count2 = seed_builtin_templates()
        assert count2 == 0


# ── Circuit Breaker Tests ───────────────────────────────────────────


class TestCircuitBreaker:
    def test_check_passes_initially(self, forven_db):
        from forven.db import create_bot
        from forven.bot_factory.circuit_breaker import check_circuit_breaker, check_llm_daily_cap

        bot_id = create_bot({"name": "CB Bot", "model": "gpt-4.1-mini"})
        assert check_circuit_breaker(bot_id) is True
        assert check_llm_daily_cap(bot_id) is True

    def test_circuit_breaker_trips_on_errors(self, forven_db):
        from forven.db import create_bot
        from forven.bot_factory.circuit_breaker import (
            check_circuit_breaker,
            record_failure,
        )

        bot_id = create_bot({
            "name": "Trip Bot",
            "model": "gpt-4.1-mini",
            "max_consecutive_errors": 3,
        })

        record_failure(bot_id)
        assert check_circuit_breaker(bot_id) is True

        record_failure(bot_id)
        assert check_circuit_breaker(bot_id) is True

        record_failure(bot_id)
        # After 3 failures, should trip
        assert check_circuit_breaker(bot_id) is False

    def test_success_resets_errors(self, forven_db):
        from forven.db import create_bot
        from forven.bot_factory.circuit_breaker import (
            check_circuit_breaker,
            record_failure,
            record_success,
        )

        bot_id = create_bot({
            "name": "Reset Bot",
            "model": "gpt-4.1-mini",
            "max_consecutive_errors": 3,
        })

        record_failure(bot_id)
        record_failure(bot_id)
        record_success(bot_id)

        assert check_circuit_breaker(bot_id) is True

    def test_llm_cap_trips(self, forven_db):
        from forven.db import create_bot
        from forven.bot_factory.circuit_breaker import check_llm_daily_cap, record_llm_call

        bot_id = create_bot({
            "name": "Cap Bot",
            "model": "gpt-4.1-mini",
            "max_llm_calls_per_day": 3,
        })

        record_llm_call(bot_id)
        record_llm_call(bot_id)
        assert check_llm_daily_cap(bot_id) is True

        record_llm_call(bot_id)
        assert check_llm_daily_cap(bot_id) is False


# ── Engine Tests ────────────────────────────────────────────────────


class TestEngine:
    def test_assemble_prompt(self):
        from forven.bot_factory.engine import assemble_prompt

        config = {
            "id": "test-id",
            "soul": "You are a careful trader.",
            "strategy": "Trade momentum.",
            "context": "BTC is volatile.",
            "guardrails": "Never go all-in.",
            "capital_allocation": 50000,
            "max_position_pct": 10,
            "max_concurrent_positions": 3,
            "max_drawdown_pct": 5,
        }

        messages = assemble_prompt(config)
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert "careful trader" in messages[0]["content"]
        assert "Never go all-in" in messages[0]["content"]
        assert messages[1]["role"] == "user"
        assert "momentum" in messages[1]["content"]
        assert "BTC is volatile" in messages[1]["content"]
        assert "$50,000" in messages[1]["content"]

    def test_assemble_prompt_tolerates_missing_history_reasoning(self):
        from forven.bot_factory.engine import assemble_prompt

        config = {
            "id": "test-id",
            "soul": "You are a careful trader.",
            "capital_allocation": 50000,
            "max_position_pct": 10,
            "max_concurrent_positions": 3,
            "max_drawdown_pct": 5,
        }

        messages = assemble_prompt(
            config,
            rolling_history=[
                {"action_type": "hold", "reasoning": None, "trade_data": None},
                None,
            ],
        )

        assert len(messages) == 2
        assert "Recent Decisions" in messages[1]["content"]

    def test_parse_llm_response_json(self):
        from forven.bot_factory.engine import _parse_llm_response

        result = _parse_llm_response('{"action": "BUY", "ticker": "BTC", "qty": 1, "reasoning": "test"}')
        assert result["action"] == "BUY"
        assert result["ticker"] == "BTC"

    def test_parse_llm_response_code_block(self):
        from forven.bot_factory.engine import _parse_llm_response

        text = 'Here is my analysis:\n```json\n{"action": "HOLD", "reasoning": "no signal"}\n```'
        result = _parse_llm_response(text)
        assert result["action"] == "HOLD"

    def test_parse_llm_response_embedded_json(self):
        from forven.bot_factory.engine import _parse_llm_response

        text = 'I think we should buy. {"action": "BUY", "ticker": "ETH", "qty": 5, "reasoning": "bullish"} That is my call.'
        result = _parse_llm_response(text)
        assert result["action"] == "BUY"

    def test_parse_llm_response_fallback(self):
        from forven.bot_factory.engine import _parse_llm_response

        result = _parse_llm_response("I have no idea what to do")
        assert result["action"] == "HOLD"

    def test_enforce_risk_limits_blocks_excess_positions(self):
        from forven.bot_factory.engine import enforce_risk_limits

        config = {"max_concurrent_positions": 2, "max_position_pct": 10, "capital_allocation": 100000}
        positions = [{"ticker": "BTC"}, {"ticker": "ETH"}]

        trade = {"action": "BUY", "ticker": "SOL", "qty": 10}
        result = enforce_risk_limits(trade, config, positions)
        assert result is None

    def test_enforce_risk_limits_allows_within_limits(self):
        from forven.bot_factory.engine import enforce_risk_limits

        config = {"max_concurrent_positions": 5, "max_position_pct": 10, "capital_allocation": 100000}
        positions = [{"ticker": "BTC"}]

        trade = {"action": "BUY", "ticker": "ETH", "qty": 5}
        result = enforce_risk_limits(trade, config, positions)
        assert result is not None
        assert result["action"] == "BUY"

    def test_enforce_risk_limits_passes_hold(self):
        from forven.bot_factory.engine import enforce_risk_limits

        config = {"max_concurrent_positions": 1}
        result = enforce_risk_limits({"action": "HOLD"}, config, [{"ticker": "BTC"}])
        assert result is not None

    def test_enforce_risk_limits_blocks_oversized_position_value(self):
        """LLM-specified qty must not exceed max_position_pct of capital."""
        from forven.bot_factory.engine import enforce_risk_limits

        config = {"max_concurrent_positions": 5, "max_position_pct": 10, "capital_allocation": 100000}
        # 10% of 100k = $10k max; 1 BTC @ $50k would be 50% — must block
        trade = {"action": "BUY", "ticker": "BTC", "qty": 1}
        market_event = {"pairs": {"BTC": {"current_price": 50000}}}

        result = enforce_risk_limits(trade, config, [], market_event)
        assert result is None

    def test_enforce_risk_limits_allows_sized_position(self):
        from forven.bot_factory.engine import enforce_risk_limits

        config = {"max_concurrent_positions": 5, "max_position_pct": 10, "capital_allocation": 100000}
        # 0.1 BTC @ $50k = $5k, well under $10k limit
        trade = {"action": "BUY", "ticker": "BTC", "qty": 0.1}
        market_event = {"pairs": {"BTC": {"current_price": 50000}}}

        result = enforce_risk_limits(trade, config, [], market_event)
        assert result is not None

    def test_memory_query_builder_reflects_market_state(self):
        """Query must vary with market direction so recall returns different memories."""
        from forven.bot_factory.runner import _build_memory_query

        up_event = {"pairs": {"BTC": {"change_pct": 3.2, "volatility": 2.5}}}
        down_event = {"pairs": {"BTC": {"change_pct": -4.1, "volatility": 2.5}}}

        up_q = _build_memory_query(up_event, [])
        down_q = _build_memory_query(down_event, [])

        assert "up" in up_q.lower()
        assert "down" in down_q.lower()
        assert up_q != down_q

    def test_memory_query_builder_includes_holdings(self):
        from forven.bot_factory.runner import _build_memory_query

        positions = [{"ticker": "ETH", "direction": "long"}]
        q = _build_memory_query({"pairs": {}}, positions)
        assert "ETH" in q
        assert "long" in q

    def test_memory_query_builder_handles_no_data(self):
        from forven.bot_factory.runner import _build_memory_query

        assert _build_memory_query(None, None)  # returns *something*, not empty

    def test_unrealized_pnl_long(self):
        from forven.bot_factory.runner import _compute_unrealized_pnl

        positions = [{"direction": "long", "entry_price": 100, "current_price": 110, "qty": 5}]
        assert _compute_unrealized_pnl(positions) == 50

    def test_unrealized_pnl_short(self):
        from forven.bot_factory.runner import _compute_unrealized_pnl

        positions = [{"direction": "short", "entry_price": 100, "current_price": 90, "qty": 5}]
        assert _compute_unrealized_pnl(positions) == 50

    def test_unrealized_pnl_empty(self):
        from forven.bot_factory.runner import _compute_unrealized_pnl

        assert _compute_unrealized_pnl(None) == 0.0
        assert _compute_unrealized_pnl([]) == 0.0

    def test_drawdown_pct_trips_when_below_peak(self):
        from forven.bot_factory.runner import _drawdown_pct

        # Peak 110, now 99 → drawdown = 10%
        assert abs(_drawdown_pct(110, 99) - 10.0) < 1e-9

    def test_drawdown_pct_zero_when_at_or_above_peak(self):
        from forven.bot_factory.runner import _drawdown_pct

        assert _drawdown_pct(100, 100) == 0.0
        assert _drawdown_pct(100, 105) == 0.0  # Above peak → no drawdown

    def test_drawdown_enforcement_flow(self):
        """End-to-end: peak-to-trough drawdown past the limit should trip the pause."""
        from forven.bot_factory.runner import _compute_unrealized_pnl, _drawdown_pct

        starting_capital = 100_000.0
        realized_pnl = 0.0
        peak_equity = starting_capital
        max_dd = 3.0  # 3%

        # Simulate: bot opens a position that gains, then loses hard
        positions = [{"direction": "long", "entry_price": 100, "current_price": 110, "qty": 50}]
        equity_up = starting_capital + realized_pnl + _compute_unrealized_pnl(positions)
        peak_equity = max(peak_equity, equity_up)
        assert _drawdown_pct(peak_equity, equity_up) == 0.0  # At peak, no dd

        # Now price drops hard — position goes to -$5000 unrealized on $100k capital
        positions[0]["current_price"] = 0  # total wipeout on the position
        equity_down = starting_capital + realized_pnl + _compute_unrealized_pnl(positions)
        dd = _drawdown_pct(peak_equity, equity_down)
        assert dd > max_dd  # Breach detected

    def test_decision_cycle_circuit_breaker(self, forven_db):
        import asyncio
        from forven.db import create_bot
        from forven.bot_factory.engine import run_decision_cycle
        from forven.bot_factory.circuit_breaker import record_failure

        bot_id = create_bot({
            "name": "CB Test",
            "model": "gpt-4.1-mini",
            "max_consecutive_errors": 2,
        })

        record_failure(bot_id)
        record_failure(bot_id)

        config = {"id": bot_id, "model": "gpt-4.1-mini", "max_consecutive_errors": 2}
        result = asyncio.run(run_decision_cycle(config))
        assert result.action_type == "paused"
        assert "circuit breaker" in result.error.lower()

    def test_decision_cycle_uses_configured_model_without_fallback(self, forven_db):
        import asyncio
        from forven.bot_factory import engine

        config = {
            "id": str(uuid4()),
            "name": "Strict Model Bot",
            "model": "gpt-4.1-mini",
        }

        with (
            patch.object(engine, "check_circuit_breaker", return_value=True),
            patch.object(engine, "check_llm_daily_cap", return_value=True),
            patch.object(engine, "record_llm_call"),
            patch.object(engine, "record_success"),
            patch.object(engine, "log_bot_decision"),
            patch("forven.ai.normalize_provider_and_model", return_value=("openai", "gpt-4.1-mini")) as normalize_mock,
            patch("forven.ai.call_ai", new_callable=AsyncMock, return_value='{"action":"HOLD","reasoning":"stay flat"}') as call_ai_mock,
        ):
            result = asyncio.run(engine.run_decision_cycle(config))

        normalize_mock.assert_called_once_with("auto", "gpt-4.1-mini")
        call_ai_mock.assert_awaited_once()
        assert call_ai_mock.await_args.kwargs["provider"] == "openai"
        assert call_ai_mock.await_args.kwargs["model"] == "gpt-4.1-mini"
        assert call_ai_mock.await_args.kwargs["fallback"] is False
        assert result.action_type == "pass"
        assert result.reasoning == "stay flat"


# ── Pydantic Model Tests ────────────────────────────────────────────


class TestModels:
    def test_bot_config_create_defaults(self):
        from forven.bot_factory.models import BotConfigCreate

        config = BotConfigCreate()
        assert config.name == "Untitled Bot"
        assert config.model == "gpt-4.1-mini"
        assert config.capital_allocation == 100_000
        assert config.max_consecutive_errors == 5

    def test_bot_config_update_partial(self):
        from forven.bot_factory.models import BotConfigUpdate

        update = BotConfigUpdate(name="New Name")
        d = update.model_dump(exclude_none=True)
        assert d == {"name": "New Name"}


# ── API Router Tests ────────────────────────────────────────────────


class TestAPIRoutes:
    def test_list_bots_empty(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)
        response = client.get("/api/bot-factory/bots")
        assert response.status_code == 200
        assert response.json() == []

    def test_create_and_get_bot(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)

        # Create
        response = client.post("/api/bot-factory/bots", json={
            "name": "API Bot",
            "model": "gpt-4.1-mini",
            "soul": "Helpful trader",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "API Bot"
        bot_id = data["id"]

        # Get
        response = client.get(f"/api/bot-factory/bots/{bot_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "API Bot"

    def test_update_bot(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)
        resp = client.post("/api/bot-factory/bots", json={"name": "Before"})
        bot_id = resp.json()["id"]

        resp = client.put(f"/api/bot-factory/bots/{bot_id}", json={"name": "After"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "After"

    def test_delete_bot(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)
        resp = client.post("/api/bot-factory/bots", json={"name": "Delete Me"})
        bot_id = resp.json()["id"]

        resp = client.delete(f"/api/bot-factory/bots/{bot_id}")
        assert resp.status_code == 200

        resp = client.get(f"/api/bot-factory/bots/{bot_id}")
        assert resp.status_code == 404

    def test_clone_bot(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)
        resp = client.post("/api/bot-factory/bots", json={"name": "Original", "soul": "Cool"})
        bot_id = resp.json()["id"]

        resp = client.post(f"/api/bot-factory/bots/{bot_id}/clone", json={"new_name": "Cloned"})
        assert resp.status_code == 200
        assert resp.json()["name"] == "Cloned"
        assert resp.json()["soul"] == "Cool"

    def test_templates_crud(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)

        # Create template
        resp = client.post("/api/bot-factory/templates", json={
            "name": "My Template",
            "description": "Test template",
            "config": {"soul": "Aggressive", "model": "gpt-4.1"},
        })
        assert resp.status_code == 200
        tid = resp.json()["id"]

        # List templates
        resp = client.get("/api/bot-factory/templates")
        assert resp.status_code == 200
        assert len(resp.json()) >= 1

        # Get template
        resp = client.get(f"/api/bot-factory/templates/{tid}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "My Template"

    def test_bot_not_found(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)
        resp = client.get("/api/bot-factory/bots/nonexistent")
        assert resp.status_code == 404

    def test_kill_all(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)
        resp = client.post("/api/bot-factory/kill-all")
        assert resp.status_code == 200
        assert resp.json()["stopped"] == 0

    def test_decisions_empty(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)
        resp = client.post("/api/bot-factory/bots", json={"name": "D Bot"})
        bot_id = resp.json()["id"]

        resp = client.get(f"/api/bot-factory/bots/{bot_id}/decisions")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_versions_empty(self, forven_db):
        from fastapi.testclient import TestClient
        from forven.api import app

        client = TestClient(app)
        resp = client.post("/api/bot-factory/bots", json={"name": "V Bot"})
        bot_id = resp.json()["id"]

        resp = client.get(f"/api/bot-factory/bots/{bot_id}/versions")
        assert resp.status_code == 200
        assert resp.json() == []


# ── Paper Trading: Close / Slippage / Fees / SL-TP / Rehydration ────


class TestBotPaperTrading:
    """Phase A–C: closing trades, multi-lot matching, fees/slippage, SL/TP,
    rehydration, equity state, orphan reconcile."""

    def _mk_bot(self, fee_bps: float = 0.0, slip_bps: float = 0.0):
        from forven.db import create_bot
        return create_bot({
            "name": "PaperBot",
            "model": "gpt-4.1-mini",
            "taker_fee_bps": fee_bps,
            "slippage_bps": slip_bps,
        })

    def test_close_bot_trade_updates_status_and_pnl(self, forven_db):
        """SELL closes the OPEN row instead of inserting a new short row."""
        from forven.db import close_bot_trade, execute_bot_trade, get_db

        bot_id = self._mk_bot()
        trade_id = execute_bot_trade(
            bot_id=bot_id, ticker="BTC/USDT", direction="long",
            qty=1, price=50_000.0, signal_price=50_000.0,
        )
        result = close_bot_trade(trade_id, exit_price=51_000.0, reason="test")
        assert result and result.get("updated")
        assert result["pnl_usd"] == pytest.approx(1000.0, abs=0.01)

        with get_db() as conn:
            row = conn.execute(
                "SELECT status, pnl_usd FROM trades WHERE id = ?", (trade_id,)
            ).fetchone()
        assert row["status"] == "CLOSED"
        assert row["pnl_usd"] == pytest.approx(1000.0, abs=0.01)

    def test_close_bot_trade_deducts_fees(self, forven_db):
        """Entry + exit fees are subtracted from gross P&L at close."""
        from forven.db import close_bot_trade, execute_bot_trade

        bot_id = self._mk_bot(fee_bps=10.0)
        # 10 bps on $50k notional = $50 per leg → $100 total fees
        entry_fee = 50_000.0 * 1 * (10.0 / 10_000)
        trade_id = execute_bot_trade(
            bot_id=bot_id, ticker="BTC/USDT", direction="long", qty=1,
            price=50_000.0, signal_price=50_000.0,
            entry_fee_bps=10.0, entry_fee_usd=entry_fee,
        )
        exit_fee = 51_000.0 * 1 * (10.0 / 10_000)
        result = close_bot_trade(
            trade_id, exit_price=51_000.0,
            exit_fee_bps=10.0, exit_fee_usd=exit_fee, reason="test",
        )
        # Gross $1000 − ($50 + $51) = $899
        assert result["pnl_usd"] == pytest.approx(899.0, abs=0.1)
        assert result["gross_pnl_usd"] == pytest.approx(1000.0, abs=0.1)
        assert result["total_fees_usd"] == pytest.approx(101.0, abs=0.1)

    def test_rehydrate_open_positions(self, forven_db):
        """get_open_bot_positions returns runner-shaped dicts, ignores closed rows."""
        from forven.db import (
            close_bot_trade, execute_bot_trade, get_open_bot_positions,
        )

        bot_id = self._mk_bot()
        tid_open = execute_bot_trade(
            bot_id=bot_id, ticker="BTC/USDT", direction="long",
            qty=2, price=50_000.0,
        )
        tid_closed = execute_bot_trade(
            bot_id=bot_id, ticker="ETH/USDT", direction="long",
            qty=1, price=3000.0,
        )
        close_bot_trade(tid_closed, exit_price=3100.0, reason="manual")

        positions = get_open_bot_positions(bot_id)
        assert len(positions) == 1
        p = positions[0]
        assert p["trade_id"] == tid_open
        assert p["ticker"] == "BTC/USDT"
        assert p["direction"] == "long"
        assert p["qty"] == 2
        assert p["entry_price"] == 50_000.0

    def test_rehydrate_includes_sl_tp(self, forven_db):
        """SL/TP levels from open are round-tripped via signal_data."""
        from forven.db import execute_bot_trade, get_open_bot_positions

        bot_id = self._mk_bot()
        execute_bot_trade(
            bot_id=bot_id, ticker="BTC/USDT", direction="long", qty=1,
            price=50_000.0, stop_loss_price=48_000.0, take_profit_price=55_000.0,
        )
        positions = get_open_bot_positions(bot_id)
        assert positions[0]["stop_loss_price"] == 48_000.0
        assert positions[0]["take_profit_price"] == 55_000.0

    def test_multi_lot_close_by_trade_id(self, forven_db):
        """Closing one lot does not affect other OPEN lots of same ticker."""
        from forven.db import (
            close_bot_trade, execute_bot_trade, get_open_bot_positions,
        )

        bot_id = self._mk_bot()
        tid_a = execute_bot_trade(
            bot_id=bot_id, ticker="BTC/USDT", direction="long",
            qty=1, price=50_000.0,
        )
        tid_b = execute_bot_trade(
            bot_id=bot_id, ticker="BTC/USDT", direction="long",
            qty=2, price=51_000.0,
        )
        close_bot_trade(tid_a, exit_price=52_000.0, reason="test")

        remaining = get_open_bot_positions(bot_id)
        assert len(remaining) == 1
        assert remaining[0]["trade_id"] == tid_b
        assert remaining[0]["qty"] == 2

    def test_equity_state_persists(self, forven_db):
        """realized_pnl and peak_equity survive independent reads, as they
        would across a bot restart."""
        from forven.db import (
            create_bot, get_bot_equity_state, set_bot_status,
            update_bot_equity_state,
        )

        bot_id = create_bot({"name": "EquityBot", "model": "gpt-4.1-mini"})
        set_bot_status(bot_id, "stopped")
        update_bot_equity_state(
            bot_id, realized_pnl=250.0, peak_equity=100_250.0,
        )
        state = get_bot_equity_state(bot_id)
        assert state["realized_pnl"] == pytest.approx(250.0)
        assert state["peak_equity"] == pytest.approx(100_250.0)

    def test_reset_equity_state(self, forven_db):
        from forven.db import (
            create_bot, get_bot_equity_state, reset_bot_equity_state,
            set_bot_status, update_bot_equity_state,
        )

        bot_id = create_bot({"name": "B", "model": "gpt-4.1-mini"})
        set_bot_status(bot_id, "stopped")
        update_bot_equity_state(bot_id, realized_pnl=500.0, peak_equity=100500.0)
        reset_bot_equity_state(bot_id)
        state = get_bot_equity_state(bot_id)
        assert state["realized_pnl"] == 0
        assert state["peak_equity"] is None

    def test_slippage_adjusts_fill_price(self):
        """_apply_slippage: BUY fills above mid, SELL below, proportional to bps."""
        from forven.bot_factory.runner import _apply_slippage

        assert _apply_slippage(100.0, True, 10.0) == pytest.approx(100.1)
        assert _apply_slippage(100.0, False, 10.0) == pytest.approx(99.9)
        assert _apply_slippage(100.0, True, 0) == 100.0
        assert _apply_slippage(0, True, 10.0) == 0

    def test_fee_usd(self):
        """_fee_usd converts bps against absolute notional."""
        from forven.bot_factory.runner import _fee_usd

        assert _fee_usd(10_000, 10) == pytest.approx(10.0)
        assert _fee_usd(-10_000, 10) == pytest.approx(10.0)  # uses abs()
        assert _fee_usd(10_000, 0) == 0
        assert _fee_usd(10_000, None) == 0

    def test_sl_tp_trigger_long(self):
        """Long: SL triggers when price <= SL, TP when price >= TP."""
        from forven.bot_factory.runner import _check_sl_tp_trigger

        base = {
            "direction": "long", "entry_price": 100,
            "stop_loss_price": 95, "take_profit_price": 105,
        }
        assert _check_sl_tp_trigger({**base, "current_price": 94}) == "stop_loss"
        assert _check_sl_tp_trigger({**base, "current_price": 106}) == "take_profit"
        assert _check_sl_tp_trigger({**base, "current_price": 100}) is None
        assert _check_sl_tp_trigger({**base, "current_price": None}) is None

    def test_sl_tp_trigger_short(self):
        """Short: SL triggers when price >= SL, TP when price <= TP."""
        from forven.bot_factory.runner import _check_sl_tp_trigger

        base = {
            "direction": "short", "entry_price": 100,
            "stop_loss_price": 105, "take_profit_price": 95,
        }
        assert _check_sl_tp_trigger({**base, "current_price": 106}) == "stop_loss"
        assert _check_sl_tp_trigger({**base, "current_price": 94}) == "take_profit"

    def test_compute_sl_tp_prices(self):
        from forven.bot_factory.runner import _compute_sl_tp_prices

        sl, tp = _compute_sl_tp_prices(100, "long", 5, 10)
        assert sl == pytest.approx(95.0)
        assert tp == pytest.approx(110.0)

        sl, tp = _compute_sl_tp_prices(100, "short", 5, 10)
        assert sl == pytest.approx(105.0)
        assert tp == pytest.approx(90.0)

        sl, tp = _compute_sl_tp_prices(100, "long", None, None)
        assert sl is None and tp is None

    def test_funding_accrual_prorated(self):
        """_accrue_funding_cost charges long notional * rate * elapsed_days."""
        from forven.bot_factory.runner import _accrue_funding_cost

        positions = [{
            "direction": "long", "entry_price": 50_000, "qty": 1,
        }]
        # 1 bp/day over 86400s (1 day) on $50k = $5
        cost = _accrue_funding_cost(positions, 0, 86_400, rate_bps_per_day=1.0)
        assert cost == pytest.approx(5.0, abs=0.001)

        # No time elapsed = no cost
        assert _accrue_funding_cost(positions, 100, 100, 1.0) == 0
        # No positions = no cost
        assert _accrue_funding_cost([], 0, 86_400, 1.0) == 0
        # No rate = no cost
        assert _accrue_funding_cost(positions, 0, 86_400, 0) == 0

    def test_funding_short_gets_credit(self):
        from forven.bot_factory.runner import _accrue_funding_cost

        positions = [{
            "direction": "short", "entry_price": 50_000, "qty": 1,
        }]
        cost = _accrue_funding_cost(positions, 0, 86_400, rate_bps_per_day=1.0)
        # Shorts credit the funding — cost is negative
        assert cost == pytest.approx(-5.0, abs=0.001)

    def test_mark_to_market_handles_zero_price(self):
        """_refresh_position_prices applies 0 price (wipeout) instead of skipping."""
        from forven.bot_factory.runner import BotRunner

        runner = BotRunner.__new__(BotRunner)
        positions = [{
            "ticker": "BTC/USDT", "entry_price": 50_000, "qty": 1,
            "direction": "long", "current_price": 50_000,
        }]
        market = {"pairs": {"BTC/USDT": {"current_price": 0}}}
        runner._refresh_position_prices(positions, market)
        assert positions[0]["current_price"] == 0

    def test_unrealized_pnl_wipeout(self):
        """_compute_unrealized_pnl on 0 current_price: long loses entry*qty."""
        from forven.bot_factory.runner import _compute_unrealized_pnl

        pnl = _compute_unrealized_pnl([{
            "entry_price": 100, "qty": 5, "direction": "long", "current_price": 0,
        }])
        assert pnl == pytest.approx(-500)

    def test_orphan_reconcile_closes_inactive_bots(self, forven_db):
        """reconcile_orphaned_bot_trades closes OPEN rows for bots not in active set."""
        from forven.db import (
            create_bot, execute_bot_trade, get_db,
            reconcile_orphaned_bot_trades,
        )

        bot_a = create_bot({"name": "Active", "model": "gpt-4.1-mini"})
        bot_b = create_bot({"name": "Dead", "model": "gpt-4.1-mini"})
        tid_a = execute_bot_trade(
            bot_id=bot_a, ticker="BTC/USDT", direction="long", qty=1, price=50_000,
        )
        tid_b = execute_bot_trade(
            bot_id=bot_b, ticker="ETH/USDT", direction="long", qty=1, price=3000,
        )

        # Only bot_a is "alive"; bot_b's trade should be closed
        reports = reconcile_orphaned_bot_trades(active_bot_ids={bot_a})
        assert len(reports) == 1
        assert reports[0]["bot_id"] == bot_b
        assert reports[0]["action"] == "closed"

        with get_db() as conn:
            row_a = conn.execute(
                "SELECT status FROM trades WHERE id = ?", (tid_a,)
            ).fetchone()
            row_b = conn.execute(
                "SELECT status FROM trades WHERE id = ?", (tid_b,)
            ).fetchone()
        assert row_a["status"] == "OPEN"
        assert row_b["status"] == "CLOSED"

    def test_orphan_reconcile_dry_run(self, forven_db):
        from forven.db import (
            create_bot, execute_bot_trade, get_db,
            reconcile_orphaned_bot_trades,
        )

        bot_id = create_bot({"name": "X", "model": "gpt-4.1-mini"})
        tid = execute_bot_trade(
            bot_id=bot_id, ticker="BTC/USDT", direction="long", qty=1, price=50_000,
        )
        reports = reconcile_orphaned_bot_trades(
            active_bot_ids=set(), dry_run=True,
        )
        assert len(reports) == 1
        assert reports[0]["action"] == "would_close"
        # Confirm no mutation
        with get_db() as conn:
            row = conn.execute(
                "SELECT status FROM trades WHERE id = ?", (tid,)
            ).fetchone()
        assert row["status"] == "OPEN"

    def test_engine_prompt_uses_realized_pnl(self, forven_db):
        """assemble_prompt reflects realized_pnl in Available Cash / Equity."""
        from forven.bot_factory.engine import assemble_prompt

        config = {
            "name": "Test", "soul": "s", "context": "c",
            "capital_allocation": 100_000, "max_position_pct": 10,
            "max_concurrent_positions": 5, "max_drawdown_pct": 3,
        }
        messages = assemble_prompt(
            bot_config=config, market_event=None, positions=None,
            memory_results=None, rolling_history=None, realized_pnl=1250.0,
        )
        blob = "\n".join(m.get("content", "") for m in messages)
        assert "Realized P&L" in blob
        assert "1,250" in blob
        assert "Starting Capital" in blob

    def test_positions_api_endpoint(self, forven_db):
        """/api/bot-factory/bots/{id}/positions returns snapshot with open rows."""
        from fastapi.testclient import TestClient
        from forven.api import app
        from forven.db import create_bot, execute_bot_trade

        bot_id = create_bot({
            "name": "API", "model": "gpt-4.1-mini",
            "capital_allocation": 100_000,
        })
        execute_bot_trade(
            bot_id=bot_id, ticker="BTC/USDT", direction="long", qty=1,
            price=50_000.0, stop_loss_price=48_000.0, take_profit_price=55_000.0,
        )

        client = TestClient(app)
        resp = client.get(f"/api/bot-factory/bots/{bot_id}/positions")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bot_id"] == bot_id
        assert data["starting_capital"] == 100_000
        assert len(data["open_positions"]) == 1
        pos = data["open_positions"][0]
        assert pos["ticker"] == "BTC/USDT"
        assert pos["stop_loss_price"] == 48_000.0
        assert pos["take_profit_price"] == 55_000.0
