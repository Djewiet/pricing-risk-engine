"""Bootstrap of a discount curve from par yields.

A *par yield* for maturity ``T`` is the coupon rate ``c`` that makes a fixed-rate bond issued
today price at par (100). With accrual fractions ``tau_i`` and payment dates ``t_i``:

    1 = c * sum_i tau_i * P(t_i) + P(T)        =>      c = (1 - P(T)) / sum_i tau_i * P(t_i)

The bootstrap walks through the quotes by increasing maturity. Each quote adds one pillar at
its maturity, whose discount factor is solved so that the bond reprices exactly at par, the
previous pillars being already fixed. Coupons falling between the previous pillar and the new
one are discounted with the log-linear interpolation, so they depend on the unknown pillar:
the equation is solved with Brent's method on the pillar zero rate.

Because log-linear interpolation is local, solving pillar ``k`` never moves pillars ``< k``,
so a single forward pass is exact (no global iteration is needed).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
from scipy.optimize import brentq

from pricer.dates.daycount import ACT_365F, ActualActualICMA, DayCount
from pricer.dates.schedule import Schedule
from pricer.dates.tenor import Tenor, TenorUnit
from pricer.errors import BootstrapError, MarketDataError
from pricer.market.curves import DiscountCurve, YieldCurve

#: Bracket on the continuously-compounded zero rate of the pillar being solved.
_ZERO_RATE_BRACKET = (-0.5, 1.0)
_SOLVER_TOLERANCE = 1e-14


@dataclass(frozen=True, slots=True)
class ParYieldQuote:
    """Par yield of a fixed-rate bullet bond issued at the curve reference date.

    Attributes:
        tenor: Maturity of the bond, from the reference date.
        rate: Par yield as a decimal (``0.0425`` for 4.25%).
    """

    tenor: Tenor
    rate: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.rate):
            msg = f"Par yield for {self.tenor} must be finite, got {self.rate}"
            raise MarketDataError(msg)


@dataclass(frozen=True, slots=True)
class ParBondConvention:
    """Conventions of the par bonds behind the quotes.

    The default matches US Treasury coupon securities: semi-annual coupons, ACT/ACT ICMA,
    unadjusted dates, settlement on the reference date.

    Attributes:
        frequency: Coupons per year.
        coupon_day_count: Accrual convention of the coupons. ``None`` means ACT/ACT ICMA at
            the bond frequency.
    """

    frequency: int = 2
    coupon_day_count: DayCount | None = None

    def __post_init__(self) -> None:
        if self.frequency <= 0 or 12 % self.frequency != 0:
            msg = f"Frequency must divide 12, got {self.frequency}"
            raise ValueError(msg)

    @property
    def period(self) -> Tenor:
        """Length of a regular coupon period."""
        return Tenor(12 // self.frequency, TenorUnit.MONTHS)

    @property
    def day_count(self) -> DayCount:
        """Effective coupon day count."""
        return self.coupon_day_count or ActualActualICMA(self.frequency)


@dataclass(frozen=True, slots=True)
class _ParBond:
    """Cash-flow skeleton of a par bond: payment dates and coupon accrual fractions."""

    maturity: date
    payment_dates: tuple[date, ...]
    accruals: tuple[float, ...]

    @classmethod
    def build(cls, effective: date, maturity: date, convention: ParBondConvention) -> _ParBond:
        schedule = Schedule(effective, maturity, convention.period)
        day_count = convention.day_count
        periods = schedule.periods
        return cls(
            maturity=maturity,
            payment_dates=tuple(p.end for p in periods),
            accruals=tuple(
                day_count.year_fraction(p.start, p.end, p.ref_start, p.ref_end) for p in periods
            ),
        )

    def annuity(self, curve: YieldCurve) -> float:
        times = np.array([curve.time(d) for d in self.payment_dates], dtype=np.float64)
        return float(np.dot(self.accruals, curve.discount_factors(times)))

    def par_yield(self, curve: YieldCurve) -> float:
        return (1.0 - curve.discount(self.maturity)) / self.annuity(curve)


def par_yield(
    curve: YieldCurve,
    maturity: date,
    convention: ParBondConvention | None = None,
) -> float:
    """Par yield implied by ``curve`` for a bond issued at the reference date.

    This is the inverse of the bootstrap: feeding a bootstrapped curve back in returns the
    input quotes, which is the primary consistency check of the bootstrap.
    """
    bond = _ParBond.build(curve.reference_date, maturity, convention or ParBondConvention())
    return bond.par_yield(curve)


def bootstrap_par_yield_curve(
    reference_date: date,
    quotes: Iterable[ParYieldQuote],
    convention: ParBondConvention | None = None,
    curve_day_count: DayCount = ACT_365F,
) -> DiscountCurve:
    """Bootstrap a log-linear discount curve that reprices every par bond exactly.

    Args:
        reference_date: Valuation date; bonds are issued and settle on this date.
        quotes: Par yields, in any order. Maturities must be distinct.
        convention: Bond conventions (defaults to US Treasury conventions).
        curve_day_count: Day count of the resulting curve time axis.

    Returns:
        A curve with one pillar per quote, at the bond maturity.

    Raises:
        MarketDataError: If no quote is given or two quotes share a maturity.
        BootstrapError: If a pillar cannot be solved within the zero-rate bracket.
    """
    convention = convention or ParBondConvention()
    bonds = sorted(
        (
            (_ParBond.build(reference_date, q.tenor.advance(reference_date), convention), q)
            for q in quotes
        ),
        key=lambda pair: pair[0].maturity,
    )
    if not bonds:
        msg = "Cannot bootstrap a curve without quotes"
        raise MarketDataError(msg)
    maturities = [bond.maturity for bond, _ in bonds]
    if len(set(maturities)) != len(maturities):
        msg = "Par yield quotes must have distinct maturities"
        raise MarketDataError(msg)

    pillar_dates: list[date] = []
    pillar_discounts: list[float] = []
    for bond, quote in bonds:
        discount = _solve_pillar(
            reference_date,
            pillar_dates=pillar_dates,
            pillar_discounts=pillar_discounts,
            bond=bond,
            quote=quote,
            curve_day_count=curve_day_count,
        )
        pillar_dates.append(bond.maturity)
        pillar_discounts.append(discount)

    return DiscountCurve(reference_date, pillar_dates, pillar_discounts, curve_day_count)


def _solve_pillar(
    reference_date: date,
    *,
    pillar_dates: Sequence[date],
    pillar_discounts: Sequence[float],
    bond: _ParBond,
    quote: ParYieldQuote,
    curve_day_count: DayCount,
) -> float:
    """Solve the discount factor of a new pillar at ``bond.maturity``."""
    t = curve_day_count.year_fraction(reference_date, bond.maturity)
    dates = (*pillar_dates, bond.maturity)

    def residual(zero_rate: float) -> float:
        trial = DiscountCurve(
            reference_date, dates, (*pillar_discounts, math.exp(-zero_rate * t)), curve_day_count
        )
        return bond.par_yield(trial) - quote.rate

    try:
        zero_rate = brentq(residual, *_ZERO_RATE_BRACKET, xtol=_SOLVER_TOLERANCE)
    except ValueError as exc:
        msg = f"Cannot solve the {quote.tenor} pillar for par yield {quote.rate:.6%}"
        raise BootstrapError(msg) from exc
    return math.exp(-zero_rate * t)
