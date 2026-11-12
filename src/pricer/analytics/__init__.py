"""Instrument analytics that do not need a market snapshot (yields, durations)."""

from pricer.analytics.bond import (
    YieldAnalytics,
    yield_analytics,
    yield_times,
    yield_to_maturity,
    z_spread,
)

__all__ = [
    "YieldAnalytics",
    "yield_analytics",
    "yield_times",
    "yield_to_maturity",
    "z_spread",
]
