"""Greeks by bump-and-revalue, for any pricing method.

Each Greek is a finite difference of the value under bumped copies of the market snapshot:

* delta, gamma: central differences on the spot, ``S (1 +/- h)``;
* vega: central difference on a parallel shift of the volatility surface;
* rho, dividend rho: central differences on a parallel zero-rate shift of the discount
  and dividend curves (:class:`~pricer.market.curves.ZeroSpreadedCurve`);
* theta: forward difference over ``days`` calendar days of
  :meth:`~pricer.market.snapshot.MarketSnapshot.roll_forward`.

Central differences have an O(h^2) truncation error; the second difference for gamma also
loses about ``eps V / h^2`` to round-off, which bounds how small the spot bump can be.

The value function only sees snapshots, so the same code gives the Greeks of the closed
form, of a tree or of a Monte Carlo engine, and the risk service bumps exactly the market
objects it receives. A Monte Carlo engine must use the same random numbers for every bump
(fixed seed: common random numbers), otherwise the differences are dominated by noise.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from pricer.greeks.base import Greeks
from pricer.market.curves import ZeroSpreadedCurve
from pricer.market.snapshot import MarketSnapshot
from pricer.market.volatility import ShiftedVolatility

DAYS_PER_YEAR = 365.0


@dataclass(frozen=True, slots=True)
class BumpSizes:
    """Bump sizes of :func:`bump_greeks`.

    Attributes:
        spot_relative: Relative spot bump ``h``: the spot moves to ``S (1 +/- h)``.
        volatility: Absolute volatility shift (``1e-4`` = 0.01 vol point).
        rate: Zero-rate shift of each curve, continuously compounded (``1e-4`` = 1bp).
        days: Calendar days the market is rolled forward for theta.
    """

    spot_relative: float = 1e-3
    volatility: float = 1e-4
    rate: float = 1e-4
    days: int = 1

    def __post_init__(self) -> None:
        for name in ("spot_relative", "volatility", "rate"):
            size = getattr(self, name)
            if not (math.isfinite(size) and size > 0.0):
                msg = f"Bump size {name} must be finite and positive, got {size}"
                raise ValueError(msg)
        if self.days <= 0:
            msg = f"Theta bump must be at least one day, got {self.days}"
            raise ValueError(msg)


def bump_greeks(
    value: Callable[[MarketSnapshot], float],
    market: MarketSnapshot,
    underlying: str,
    discount_curve: str,
    *,
    dividend_curve: str | None = None,
    bumps: BumpSizes | None = None,
) -> Greeks:
    """Greeks of ``value`` by finite differences on bumped snapshots.

    Theta is the value change over ``bumps.days`` calendar days, annualised with 365 days
    per year, curves rolled with their forward rates realised. It is undefined for an
    option that expires before the rolled date (the value function then raises).

    Args:
        value: Maps a snapshot to a value, e.g. ``lambda m: engine.price(option, m).npv``.
        market: Base market; never modified, bumped copies are built instead.
        underlying: Identifier of the spot and volatility surface to bump.
        discount_curve: Curve bumped for rho.
        dividend_curve: Curve bumped for dividend rho; ``None`` gives a zero dividend rho.
        bumps: Bump sizes; the defaults suit closed forms and trees.

    Returns:
        The Greeks in the units of :class:`~pricer.greeks.base.Greeks`.
    """
    sizes = bumps or BumpSizes()
    base = value(market)

    spot = market.spot(underlying)
    h_spot = sizes.spot_relative * spot
    up = value(market.with_spot(underlying, spot + h_spot))
    down = value(market.with_spot(underlying, spot - h_spot))

    surface = market.volatility(underlying)

    def vol_bumped(shift: float) -> float:
        return value(market.with_volatility(underlying, ShiftedVolatility(surface, shift)))

    def curve_derivative(name: str) -> float:
        curve = market.curve(name)
        shifted_up = value(market.with_curve(name, ZeroSpreadedCurve(curve, sizes.rate)))
        shifted_down = value(market.with_curve(name, ZeroSpreadedCurve(curve, -sizes.rate)))
        return (shifted_up - shifted_down) / (2.0 * sizes.rate)

    later = value(market.roll_forward(sizes.days))
    h_vol = sizes.volatility
    return Greeks(
        delta=(up - down) / (2.0 * h_spot),
        gamma=(up - 2.0 * base + down) / (h_spot * h_spot),
        vega=(vol_bumped(h_vol) - vol_bumped(-h_vol)) / (2.0 * h_vol),
        theta=(later - base) * DAYS_PER_YEAR / sizes.days,
        rho=curve_derivative(discount_curve),
        dividend_rho=curve_derivative(dividend_curve) if dividend_curve else 0.0,
    )
