"""Pydantic models for Bot Factory."""

from __future__ import annotations

from pydantic import BaseModel


class BotConfigCreate(BaseModel):
    """Request body for creating a bot."""

    name: str = "Untitled Bot"
    model: str = "gpt-4.1-mini"
    soul: str | None = None
    context: str | None = None
    strategy: str | None = None
    guardrails: str | None = None
    capital_allocation: float = 100_000
    max_position_pct: float = 10.0
    max_concurrent_positions: int = 5
    max_drawdown_pct: float = 3.0
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    taker_fee_bps: float = 0.0
    slippage_bps: float = 0.0
    funding_rate_bps_per_day: float = 0.0
    cooldown_seconds: int = 60
    session_hours: dict | None = None
    reasoning_verbosity: str = "standard"
    asset_mode: str = "free_roam"
    locked_pairs: list[str] | None = None
    tools: list[dict] | None = None
    web_allowlist: list[str] | None = None
    web_rate_limit: int = 10
    data_sources: dict | None = None
    max_llm_calls_per_day: int = 200
    max_consecutive_errors: int = 5
    template_id: str | None = None


class BotConfigUpdate(BaseModel):
    """Request body for updating a bot."""

    name: str | None = None
    model: str | None = None
    soul: str | None = None
    context: str | None = None
    strategy: str | None = None
    guardrails: str | None = None
    capital_allocation: float | None = None
    max_position_pct: float | None = None
    max_concurrent_positions: int | None = None
    max_drawdown_pct: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None
    taker_fee_bps: float | None = None
    slippage_bps: float | None = None
    funding_rate_bps_per_day: float | None = None
    cooldown_seconds: int | None = None
    session_hours: dict | None = None
    reasoning_verbosity: str | None = None
    asset_mode: str | None = None
    locked_pairs: list[str] | None = None
    tools: list[dict] | None = None
    web_allowlist: list[str] | None = None
    web_rate_limit: int | None = None
    data_sources: dict | None = None
    max_llm_calls_per_day: int | None = None
    max_consecutive_errors: int | None = None


class BotCloneRequest(BaseModel):
    """Request body for cloning a bot."""

    new_name: str


class BotTemplateCreate(BaseModel):
    """Request body for saving a bot config as a template."""

    name: str
    description: str | None = None
    config: dict
