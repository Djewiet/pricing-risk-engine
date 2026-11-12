"""Yield-based bond analytics: yield to maturity, durations, convexity, z-spread.

Yield convention ("street convention"): the yield ``y`` is compounded at the coupon
frequency ``f``, and a cash flow at yield-time ``t`` is discounted by
``(1 + y/f) ** (-f t)``. Yield-times are accumulated period by period with the bond's own
day count, so with ACT/ACT ICMA each regular period counts exactly ``1/f``: the price is
then the textbook ``sum CF_k / (1 + y/f)^(k - 1 + w)``, ``w`` being the fraction of the
current period left to run. This matches QuantLib's ``BondFunctions`` with
``Compounded`` at the bond frequency.

With ``P(y) = sum_k CF_k (1 + y/f)^(-f t_k)`` the dirty price per 100 of face:

* Macaulay duration ``D = sum_k t_k CF_k (1 + y/f)^(-f t_k) / P``, the PV-weighted average
  time of the cash flows;
* modified duration ``D_mod = -P'(y) / P = D / (1 + y/f)``;
* convexity ``C = P''(y) / P = sum_k CF_k t_k (t_k + 1/f) (1 + y/f)^(-f t_k - 2) / P``;
* yield DV01 ``= -P'(y) * 1bp``, the price change for a 1bp fall in yield.

Second-order price change: ``dP / P ~ -D_mod dy + C dy^2 / 2``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import brentq

from pricer.engines.bond import discount_bond
from pricer.errors import PricerError
from pricer.instruments.bond import FixedRateBond
from pricer.instruments.cashflows import FixedCoupon
from pricer.market.curves import FloatArray, YieldCurve, ZeroSpreadedCurve
from pricer.risk.curve import ONE_BP

_YIELD_BRACKET = (-0.5, 2.0)
_SPREAD_BRACKET = (-0.5, 2.0)
_SOLVER_TOLERANCE = 1e-14


@dataclass(frozen=True, slots=True)
class YieldAnalytics:
    """Price and yield risk measures of a bond at a given yield.

    Prices are per 100 of face; durations are in years.

    Attributes:
        yield_rate: Yield to maturity, compounded at the coupon frequency.
        dirty_price: Full price per 100 of face.
        clean_price: Quoted price per 100 of face.
        accrued_interest: Accrued interest per 100 of face.
        macaulay_duration: PV-weighted average yield-time of the cash flows.
        modified_duration: Relative price sensitivity ``-P'(y) / P``.
        convexity: ``P''(y) / P``.
        dv01: Price change per 100 of face for a 1bp fall in yield.
    """

    yield_rate: float
    dirty_price: float
    clean_price: float
    accrued_interest: float
    macaulay_duration: float
    modified_duration: float
    convexity: float
    dv01: float


def yield_times(bond: FixedRateBond, settlement: date) -> tuple[FloatArray, FloatArray]:
    """Remaining cash flows per 100 of face and their yield-times from ``settlement``.

    The first remaining coupon contributes the unexpired part of its period, measured as
    ``yf(start, end) - yf(start, settlement)`` so that the result is right for any day
    count; each following period adds its full year fraction.

    Raises:
        PricerError: If ``settlement`` is before issue or on or after maturity.
    """
    if settlement < bond.issue_date:
        msg = f"Yield analytics need settlement ({settlement}) on or after issue"
        raise PricerError(msg)
    flows = bond.remaining_cashflows(settlement)
    if not flows:
        msg = f"Bond maturing on {bond.maturity} has no cash flow after {settlement}"
        raise PricerError(msg)

    day_count = bond.accrual_day_count
    scale = 100.0 / bond.face_amount
    times: list[float] = []
    amounts: list[float] = []
    elapsed = 0.0
    for cf in flows:
        if isinstance(cf, FixedCoupon):
            period = cf.accrual
            if cf.accrual_start < settlement:
                period -= day_count.year_fraction(
                    cf.accrual_start, settlement, cf.ref_start, cf.ref_end
                )
            elapsed += period
        times.append(elapsed)
        amounts.append(cf.amount * scale)
    return np.array(amounts, dtype=np.float64), np.array(times, dtype=np.float64)


def yield_analytics(bond: FixedRateBond, yield_rate: float, settlement: date) -> YieldAnalytics:
    """Price, durations, convexity and DV01 of ``bond`` at ``yield_rate``.

    Raises:
        PricerError: If ``settlement`` is outside the life of the bond.
        ValueError: If ``1 + yield_rate / frequency`` is not positive.
    """
    f = bond.frequency
    growth = 1.0 + yield_rate / f
    if growth <= 0.0:
        msg = f"Yield {yield_rate} must be greater than -{f}"
        raise ValueError(msg)
    amounts, times = yield_times(bond, settlement)
    discounted = amounts * growth ** (-f * times)
    dirty = float(discounted.sum())
    slope = float(np.dot(times, discounted)) / growth  # -P'(y)
    curvature = float(np.dot(times * (times + 1.0 / f), discounted)) / growth**2  # P''(y)
    accrued = bond.accrued_interest(settlement)
    return YieldAnalytics(
        yield_rate=yield_rate,
        dirty_price=dirty,
        clean_price=dirty - accrued,
        accrued_interest=accrued,
        macaulay_duration=slope * growth / dirty,
        modified_duration=slope / dirty,
        convexity=curvature / dirty,
        dv01=slope * ONE_BP,
    )


def yield_to_maturity(bond: FixedRateBond, clean_price: float, settlement: date) -> float:
    """Yield to maturity implied by a clean price per 100 of face.

    The price is a strictly decreasing function of the yield, so the root is unique;
    it is found with Brent's method.

    Raises:
        PricerError: If no yield in the solver bracket reproduces the price.
    """
    target = clean_price + bond.accrued_interest(settlement)
    amounts, times = yield_times(bond, settlement)
    f = bond.frequency

    def residual(y: float) -> float:
        return float(np.dot(amounts, (1.0 + y / f) ** (-f * times))) - target

    try:
        return float(brentq(residual, *_YIELD_BRACKET, xtol=_SOLVER_TOLERANCE))
    except ValueError as exc:
        msg = f"No yield in {_YIELD_BRACKET} reproduces clean price {clean_price}"
        raise PricerError(msg) from exc


def z_spread(bond: FixedRateBond, clean_price: float, curve: YieldCurve) -> float:
    """Zero-volatility spread that reprices the bond at ``clean_price``.

    It is the constant shift of the curve's continuously-compounded zero rates such that
    discounting the bond on the shifted curve gives the market price.

    The z-spread measures what the bond pays above the reference curve (credit, liquidity),
    on the whole term structure rather than at a single yield.

    Raises:
        PricerError: If no spread in the solver bracket reproduces the price.
    """

    def residual(spread: float) -> float:
        return discount_bond(bond, ZeroSpreadedCurve(curve, spread)).clean_price - clean_price

    try:
        return float(brentq(residual, *_SPREAD_BRACKET, xtol=_SOLVER_TOLERANCE))
    except ValueError as exc:
        msg = f"No z-spread in {_SPREAD_BRACKET} reproduces clean price {clean_price}"
        raise PricerError(msg) from exc
