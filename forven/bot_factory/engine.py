"""LLM Decision Engine for Bot Factory bots."""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass

from forven.bot_factory.circuit_breaker import (
    check_circuit_breaker,
    check_llm_daily_cap,
    record_failure,
    record_llm_call,
    record_success,
)
from forven.db import log_bot_decision

logger = logging.getLogger(__name__)

# Minimum seconds between LLM calls (rate limit)
MIN_LLM_INTERVAL_SECONDS = 10


@dataclass
class DecisionResult:
    """Result of a bot decision cycle."""

    action_type: str  # "trade", "observation", "pass", "error", "paused"
    reasoning: str | None = None
    trade_data: dict | None = None
    observation: str | None = None
    error: str | None = None


def assemble_prompt(
    bot_config: dict,
    market_event: dict | None = None,
    positions: list[dict] | None = None,
    memory_results: list[dict] | None = None,
    rolling_history: list[dict] | None = None,
    realized_pnl: float = 0.0,
) -> list[dict]:
    """Assemble the LLM prompt from bot config and context.

    `realized_pnl` is the session-to-date realized P&L (accumulated on each
    closed trade). It's added to capital_allocation so the "available cash"
    number the LLM sees reflects wins and losses, not just starting capital.
    """
    messages = []

    # System message: soul + guardrails
    system_parts = []
    if bot_config.get("soul"):
        system_parts.append(bot_config["soul"])
    if bot_config.get("guardrails"):
        system_parts.append(f"\n## Rules You MUST Follow\n{bot_config['guardrails']}")

    system_parts.append(
        "\n## Response Format\n"
        "Respond with a JSON object:\n"
        '{"action": "BUY"|"SELL"|"HOLD"|"OBSERVE", '
        '"ticker": "SYMBOL" or null, '
        '"confidence": 0.0-1.0, '
        '"reasoning": "2-3 sentence explanation"}\n'
        "The system will auto-calculate position size from your capital and risk limits — you do NOT need to specify qty.\n"
        "Use SELL to close an existing position (specify the ticker you want to exit).\n"
        "Use OBSERVE to note a market observation without trading. Use HOLD when no action needed."
    )

    messages.append({"role": "system", "content": "\n\n".join(system_parts)})

    # User message: context + portfolio + market data
    user_parts = []

    if bot_config.get("strategy"):
        user_parts.append(f"## Trading Strategy\n{bot_config['strategy']}")

    if bot_config.get("context"):
        user_parts.append(f"## Background Context\n{bot_config['context']}")

    # Portfolio state — capital reflects realized gains/losses to date so the
    # LLM doesn't size positions against a stale starting balance.
    starting_capital = bot_config.get("capital_allocation", 100000)
    equity = starting_capital + (realized_pnl or 0.0)
    if positions:
        used_capital = sum(p.get("qty", 0) * p.get("entry_price", 0) for p in positions)
        available = equity - used_capital
        pos_lines = []
        for p in positions:
            entry = p.get("entry_price", 0)
            current = p.get("current_price", entry)
            pnl = (current - entry) * p.get("qty", 0) if p.get("direction") == "long" else (entry - current) * p.get("qty", 0)
            pnl_pct = ((current - entry) / entry * 100) if entry else 0
            if p.get("direction") == "short":
                pnl_pct = -pnl_pct
            sl = p.get("stop_loss_price")
            tp = p.get("take_profit_price")
            extras = []
            if sl is not None:
                extras.append(f"SL ${sl:,.2f}")
            if tp is not None:
                extras.append(f"TP ${tp:,.2f}")
            extra_str = f" [{', '.join(extras)}]" if extras else ""
            pos_lines.append(
                f"- {p.get('ticker', '?')}: {p.get('direction', 'long')} {p.get('qty', 0)} @ ${entry:,.2f} "
                f"(current: ${current:,.2f}, P&L: ${pnl:,.2f} / {pnl_pct:+.2f}%){extra_str}"
            )
        user_parts.append(
            f"## Portfolio\n- Starting Capital: ${starting_capital:,.2f}\n"
            f"- Realized P&L (session): ${realized_pnl or 0:,.2f}\n"
            f"- Equity: ${equity:,.2f}\n"
            f"- Available Cash: ${available:,.2f}\n"
            f"- Open Positions ({len(positions)}):\n" + "\n".join(pos_lines)
        )
    else:
        user_parts.append(
            f"## Portfolio\n- Starting Capital: ${starting_capital:,.2f}\n"
            f"- Realized P&L (session): ${realized_pnl or 0:,.2f}\n"
            f"- Equity: ${equity:,.2f}\n"
            f"- Available Cash: ${equity:,.2f}\n"
            f"- Open Positions: None (all cash)"
        )

    # Risk limits reminder
    sl_line = ""
    if bot_config.get("stop_loss_pct") is not None:
        sl_line += f"\n- Stop-loss: {bot_config['stop_loss_pct']}% (auto-closes position)"
    if bot_config.get("take_profit_pct") is not None:
        sl_line += f"\n- Take-profit: {bot_config['take_profit_pct']}% (auto-closes position)"
    user_parts.append(
        f"## Risk Limits (enforced by system)\n"
        f"- Max position size: {bot_config.get('max_position_pct', 10)}% of equity\n"
        f"- Max concurrent positions: {bot_config.get('max_concurrent_positions', 5)}\n"
        f"- Max drawdown: {bot_config.get('max_drawdown_pct', 3)}%"
        f"{sl_line}"
    )

    # Memory
    if memory_results:
        mem_lines = [f"- {m.get('text', '')}" for m in memory_results[:5]]
        user_parts.append("## Relevant Past Observations\n" + "\n".join(mem_lines))

    # Rolling history
    if rolling_history:
        hist_lines = []
        for h in rolling_history[-5:]:
            if not isinstance(h, dict):
                continue
            reasoning = str(h.get("reasoning") or "")
            hist_lines.append(
                f"- [{h.get('action_type', '?')}] {reasoning[:100]}"
            )
        if hist_lines:
            user_parts.append("## Recent Decisions\n" + "\n".join(hist_lines))

    # Market data
    if market_event:
        user_parts.append(f"## Current Market Event\n```json\n{json.dumps(market_event, indent=2)}\n```")

    user_parts.append("\nAnalyze the situation and decide your next action.")

    messages.append({"role": "user", "content": "\n\n".join(user_parts)})

    return messages


def _parse_llm_response(text: str | None) -> dict:
    """Parse the LLM response, extracting JSON from possibly mixed text."""
    if not text:
        return {"action": "HOLD", "reasoning": "LLM returned empty/null response"}
    # Try direct JSON parse
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON in code blocks
    for marker in ("```json", "```"):
        if marker in text:
            start = text.index(marker) + len(marker)
            end = text.index("```", start) if "```" in text[start:] else len(text)
            try:
                return json.loads(text[start:end].strip())
            except (json.JSONDecodeError, ValueError):
                pass

    # Try to find JSON object in text
    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start >= 0 and brace_end > brace_start:
        try:
            return json.loads(text[brace_start : brace_end + 1])
        except json.JSONDecodeError:
            pass

    # Fallback: treat as HOLD with the response as reasoning
    return {"action": "HOLD", "reasoning": text[:200]}


def _get_current_price(ticker: str, market_event: dict | None) -> float | None:
    """Extract the current price for a ticker from market event data."""
    if not market_event:
        return None
    pairs = market_event.get("pairs", {})
    pair_data = pairs.get(ticker)
    if pair_data:
        return pair_data.get("current_price")
    return None


def enforce_risk_limits(
    trade: dict,
    bot_config: dict,
    current_positions: list[dict] | None = None,
    market_event: dict | None = None,
) -> dict | None:
    """Validate a proposed trade against hard risk limits.

    Returns the trade dict if valid, or None if blocked.
    """
    if not trade or trade.get("action") in ("HOLD", "OBSERVE", None):
        return trade

    positions = current_positions or []

    # Max concurrent positions
    max_concurrent = bot_config.get("max_concurrent_positions", 5)
    if trade.get("action") == "BUY" and len(positions) >= max_concurrent:
        logger.warning(
            "Trade blocked: max concurrent positions (%d) reached", max_concurrent
        )
        return None

    # Max position size — enforced only when we can price it. The upstream
    # auto-sizer already clamps qty it computes itself, but an LLM can
    # hand back a pre-filled qty that skips that path, so re-check here.
    if trade.get("action") == "BUY":
        capital = bot_config.get("capital_allocation", 100000)
        max_pct = bot_config.get("max_position_pct", 10) / 100.0
        qty = trade.get("qty", 0) or 0
        ticker = trade.get("ticker")
        price = _get_current_price(ticker, market_event) if ticker else None
        if qty > 0 and price and price > 0 and capital > 0:
            position_value = qty * price
            max_value = capital * max_pct
            if position_value > max_value:
                logger.warning(
                    "Trade blocked: position value $%.2f exceeds max $%.2f (%.1f%% of $%.2f)",
                    position_value, max_value, max_pct * 100, capital,
                )
                return None

    return trade


async def run_decision_cycle(
    bot_config: dict,
    market_event: dict | None = None,
    positions: list[dict] | None = None,
    memory_results: list[dict] | None = None,
    rolling_history: list[dict] | None = None,
    realized_pnl: float = 0.0,
) -> DecisionResult:
    """Run a complete decision cycle for a bot.

    Checks circuit breaker and LLM cap, assembles prompt, calls LLM,
    parses response, enforces risk limits.
    """
    bot_id = bot_config["id"]

    # Pre-flight checks
    if not check_circuit_breaker(bot_id):
        return DecisionResult(
            action_type="paused",
            error="Circuit breaker tripped — too many consecutive errors",
        )

    if not check_llm_daily_cap(bot_id):
        return DecisionResult(
            action_type="paused",
            error="Daily LLM call cap reached",
        )

    # Assemble prompt
    messages = assemble_prompt(
        bot_config,
        market_event=market_event,
        positions=positions,
        memory_results=memory_results,
        rolling_history=rolling_history,
        realized_pnl=realized_pnl,
    )

    # Determine provider from model
    model = bot_config.get("model", "gpt-4.1-mini")

    try:
        from forven.ai import call_ai, normalize_provider_and_model

        provider, resolved_model = normalize_provider_and_model("auto", model)

        # Call LLM — no fallback, strict model control
        record_llm_call(bot_id)
        response_text = await call_ai(
            provider=provider,
            model=resolved_model,
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
            fallback=False,
        )

        # Parse response
        parsed = _parse_llm_response(response_text)
        action = (parsed.get("action") or "HOLD").upper()
        reasoning = parsed.get("reasoning", "")
        verbosity = bot_config.get("reasoning_verbosity", "standard")

        # Map to result
        if action in ("BUY", "SELL"):
            ticker = parsed.get("ticker")

            if action == "BUY":
                # Auto-calculate qty from capital and current price
                qty = parsed.get("qty") or 0
                if (not qty or qty <= 0) and ticker and market_event:
                    price = _get_current_price(ticker, market_event)
                    if price and price > 0:
                        capital = bot_config.get("capital_allocation", 100000)
                        max_pct = bot_config.get("max_position_pct", 10) / 100.0
                        max_spend = capital * max_pct
                        qty = int(max_spend / price)
                        if qty <= 0:
                            qty = 1  # Minimum 1 unit
                parsed["qty"] = qty

            elif action == "SELL" and ticker and positions:
                # Find the specific lot to close (oldest-first: FIFO).
                # We pin the trade_id so the runner closes the exact row
                # we're pricing here — closing "all longs in this ticker"
                # silently loses P&L across multiple lots.
                for p in positions:
                    if p.get("ticker") == ticker:
                        parsed["qty"] = p.get("qty", 0)
                        parsed["trade_id"] = p.get("trade_id")
                        parsed["entry_price"] = p.get("entry_price")
                        parsed["direction"] = p.get("direction", "long")
                        break

            trade = enforce_risk_limits(parsed, bot_config, positions, market_event)
            if trade is None:
                result = DecisionResult(
                    action_type="pass",
                    reasoning=f"Trade blocked by risk limits: {reasoning}",
                )
            else:
                trade_data = {
                    "action": action,
                    "ticker": ticker,
                    "qty": parsed.get("qty", 0),
                    "confidence": parsed.get("confidence"),
                }
                if action == "SELL":
                    trade_data["trade_id"] = parsed.get("trade_id")
                    trade_data["entry_price"] = parsed.get("entry_price")
                    trade_data["direction"] = parsed.get("direction", "long")
                result = DecisionResult(
                    action_type="trade",
                    reasoning=reasoning,
                    trade_data=trade_data,
                )
        elif action == "OBSERVE":
            result = DecisionResult(
                action_type="observation",
                reasoning=reasoning,
                observation=reasoning,
            )
        else:
            result = DecisionResult(
                action_type="pass",
                reasoning=reasoning,
            )

        # Log decision
        log_bot_decision(
            bot_id=bot_id,
            event_trigger=market_event,
            reasoning=reasoning if verbosity != "minimal" else None,
            action_type=result.action_type,
            action_data=result.trade_data,
            verbosity=verbosity,
        )

        record_success(bot_id)
        return result

    except sqlite3.OperationalError as e:
        # Transient DB errors (e.g. "database is locked") are infrastructure
        # glitches, not decision failures — don't count toward circuit breaker.
        logger.warning("Decision cycle hit transient DB error for bot %s: %s", bot_id, e)

        try:
            log_bot_decision(
                bot_id=bot_id,
                event_trigger=market_event,
                reasoning=str(e),
                action_type="error",
                action_data={"error": str(e), "transient": True},
                verbosity="standard",
            )
        except Exception:
            pass  # DB may still be locked — don't let logging kill us

        return DecisionResult(
            action_type="error",
            error=str(e),
        )

    except Exception as e:
        logger.error("Decision cycle failed for bot %s: %s", bot_id, e)
        record_failure(bot_id)

        log_bot_decision(
            bot_id=bot_id,
            event_trigger=market_event,
            reasoning=str(e),
            action_type="error",
            action_data={"error": str(e)},
            verbosity="standard",
        )

        return DecisionResult(
            action_type="error",
            error=str(e),
        )
