"""Discounting engine for vanilla interest rate swaps, with separate forecast and discount curves.

**Floating leg.** A coupon compounding the overnight rate from ``s`` to ``e`` pays
``prod_d (1 + r_d delta_d) - 1`` per unit of notional. Under the forecast curve ``F`` each
daily factor is expected to be ``F(t_d) / F(t_{d+1})``, so the product telescopes:

    E[compounded rate] = (F(s) / F(e) - 1) / tau

This needs no day-by-day loop and no convexity adjustment when the forecast curve is the
curve of the overnight index itself. The coupon is then discounted on the discount curve
``D``: ``PV_float = sum_j N (R_j + spread) tau_j D(e_j)``.

**Fixed leg.** ``PV_fixed = K * A`` with the annuity ``A = sum_i N tau_i D(t_i)``.

**Par rate.** The fixed rate that sets the swap value to zero: ``K* = PV_float / A``.
When forecast and discount curves are the same curve and the legs start together, the
floating leg telescopes to ``N (D(t_0) - D(T))`` and
``K* = (D(t_0) - D(T)) / sum_i tau_i D(t_i)``: the single-curve par swap rate is a par
yield.

Limitation: a floating coupon whose accrual started before the valuation date needs the
overnight fixings already published, which the market snapshot does not carry yet. Such
swaps are rejected rather than priced with a guessed fixing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from pricer.errors import PricerError
from pricer.instruments.swap import InterestRateSwap
from pricer.market.curves import FloatArray, YieldCurve
from pricer.market.snapshot import MarketSnapshot


@dataclass(frozen=True, slots=True)
class SwapValuation:
    """Valuation of a swap. Amounts are in currency, rates are decimals.

    Attributes:
        valuation_date: Date the values refer to.
        npv: Value to the holder, ``sign * (floating_leg_pv - fixed_leg_pv)``.
        fixed_leg_pv: Present value of the remaining fixed coupons (positive).
        floating_leg_pv: Present value of the remaining floating coupons, spread included.
        annuity: Present value of the fixed leg per unit of fixed rate (``PV01 * 1e4``).
        par_rate: Fixed rate that would make the swap worth zero.
    """

    valuation_date: date
    npv: float
    fixed_leg_pv: float
    floating_leg_pv: float
    annuity: float
    par_rate: float


def _discount(curve: YieldCurve, dates: list[date]) -> FloatArray:
    times = np.array([curve.time(d) for d in dates], dtype=np.float64)
    return curve.discount_factors(times)


def discount_swap(
    swap: InterestRateSwap, discount_curve: YieldCurve, forecast_curve: YieldCurve
) -> SwapValuation:
    """Value ``swap`` with expected overnight rates from ``forecast_curve``.

    Raises:
        PricerError: If the curves are anchored on different dates, if the swap has no
            remaining cash flow, or if a floating coupon is already accruing.
    """
    today = discount_curve.reference_date
    if forecast_curve.reference_date != today:
        msg = (
            f"Discount curve ({today}) and forecast curve "
            f"({forecast_curve.reference_date}) must share a reference date"
        )
        raise PricerError(msg)

    fixed = [c for c in swap.fixed_leg if c.payment_date > today]
    floating = [c for c in swap.floating_leg if c.payment_date > today]
    # Both legs end on the maturity date, so they run out of cash flows together.
    if not fixed:
        msg = f"Swap matured on {swap.maturity}: no cash flow after {today}"
        raise PricerError(msg)
    if any(c.accrual_start < today for c in floating):
        msg = (
            "A floating coupon is already accruing on the valuation date: past overnight "
            "fixings are required and not supported yet"
        )
        raise PricerError(msg)

    fixed_accruals = np.array([c.accrual for c in fixed], dtype=np.float64)
    annuity = swap.notional * float(
        np.dot(fixed_accruals, _discount(discount_curve, [c.payment_date for c in fixed]))
    )
    fixed_pv = swap.fixed_rate * annuity

    float_accruals = np.array([c.accrual for c in floating], dtype=np.float64)
    starts = _discount(forecast_curve, [c.accrual_start for c in floating])
    ends = _discount(forecast_curve, [c.accrual_end for c in floating])
    forwards = (starts / ends - 1.0) / float_accruals
    float_discounts = _discount(discount_curve, [c.payment_date for c in floating])
    floating_pv = swap.notional * float(
        np.dot((forwards + swap.floating_spread) * float_accruals, float_discounts)
    )

    return SwapValuation(
        valuation_date=today,
        npv=swap.direction.sign * (floating_pv - fixed_pv),
        fixed_leg_pv=fixed_pv,
        floating_leg_pv=floating_pv,
        annuity=annuity,
        par_rate=floating_pv / annuity,
    )


@dataclass(frozen=True, slots=True)
class DiscountingSwapEngine:
    """Values swaps on two curves of the snapshot, which may be the same curve.

    Attributes:
        discount_curve: Identifier of the curve discounting all cash flows (collateral
            curve, e.g. SOFR for USD swaps under a standard CSA).
        forecast_curve: Identifier of the curve projecting the overnight rate.
    """

    discount_curve: str
    forecast_curve: str

    def price(self, instrument: InterestRateSwap, market: MarketSnapshot, /) -> SwapValuation:
        """Value ``instrument`` on the engine curves of ``market``."""
        return discount_swap(
            instrument, market.curve(self.discount_curve), market.curve(self.forecast_curve)
        )
