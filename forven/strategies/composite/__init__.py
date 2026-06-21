"""Composite strategy base classes.

Each base class pre-wires a common two-signal pattern so the agent
generates working code by filling in one abstract method rather than
writing all boilerplate from scratch.
"""

from forven.strategies.composite.trend_filter import TrendFilterStrategy
from forven.strategies.composite.momentum_confirmation import MomentumConfirmationStrategy
from forven.strategies.composite.mean_reversion_gate import MeanReversionGateStrategy
from forven.strategies.composite.funding_regime import FundingRegimeStrategy

__all__ = [
    "TrendFilterStrategy",
    "MomentumConfirmationStrategy",
    "MeanReversionGateStrategy",
    "FundingRegimeStrategy",
]
