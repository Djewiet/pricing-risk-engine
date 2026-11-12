"""Curve risk by bump-and-revalue."""

from __future__ import annotations

from collections.abc import Callable

from pricer.market.curves import ZeroSpreadedCurve
from pricer.market.snapshot import MarketSnapshot

ONE_BP = 1e-4


def parallel_dv01(
    value: Callable[[MarketSnapshot], float],
    market: MarketSnapshot,
    curve_name: str,
    bump: float = ONE_BP,
) -> float:
    """Value change for a 1bp parallel *fall* of the zero rates of one curve.

    Central difference on a :class:`ZeroSpreadedCurve`:
    ``DV01 = (V(-h) - V(+h)) / 2 * (1bp / h)``. The central scheme cancels the convexity
    term, so its error is O(h^2) instead of O(h) for a one-sided bump. Positive for a long
    bond position, by market convention.

    Args:
        value: Function mapping a snapshot to a value (e.g. an engine's NPV).
        market: Base market; never modified, bumped copies are built instead.
        curve_name: Curve to shift.
        bump: Size of the shift, as a continuously-compounded rate.
    """
    curve = market.curve(curve_name)
    down = value(market.with_curve(curve_name, ZeroSpreadedCurve(curve, -bump)))
    up = value(market.with_curve(curve_name, ZeroSpreadedCurve(curve, bump)))
    return (down - up) / 2.0 * (ONE_BP / bump)
