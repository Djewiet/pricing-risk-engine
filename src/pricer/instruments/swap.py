"""Vanilla interest rate swap: fixed leg against a compounded overnight-rate leg."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from functools import cached_property

from pricer.dates.daycount import ACT_360, DayCount
from pricer.dates.schedule import Schedule
from pricer.dates.tenor import Tenor, TenorUnit
from pricer.instruments.cashflows import FixedCoupon, OvernightCoupon

_ONE_YEAR = Tenor(1, TenorUnit.YEARS)


class SwapDirection(Enum):
    """Side of the swap, named after the fixed leg (market convention)."""

    PAYER = 1
    """Pay fixed, receive floating: gains when rates rise."""
    RECEIVER = -1
    """Receive fixed, pay floating: gains when rates fall."""

    @property
    def sign(self) -> int:
        """``+1`` for a payer, ``-1`` for a receiver: ``NPV = sign * (PV_float - PV_fixed)``."""
        return self.value


@dataclass(frozen=True)
class InterestRateSwap:
    """Vanilla fixed-for-floating swap on a daily-compounded overnight rate (e.g. SOFR).

    The instrument holds contract terms and generates both legs; it does not know which
    curves price it. Defaults follow USD SOFR OIS conventions: annual payments on both legs,
    ACT/360 on both legs. Dates are unadjusted, schedules are generated backwards from
    maturity, payments are made on accrual end dates (no payment lag).

    Attributes:
        effective_date: Start of the first accrual period on both legs.
        maturity: End of the last accrual period.
        fixed_rate: Fixed coupon rate as a decimal.
        notional: Notional in currency, identical on both legs and never exchanged.
        direction: Payer or receiver of the fixed leg.
        fixed_tenor: Fixed-leg coupon period.
        fixed_day_count: Fixed-leg accrual convention.
        floating_tenor: Floating-leg coupon period.
        floating_day_count: Floating-leg accrual convention (that of the overnight index).
        floating_spread: Spread over the compounded overnight rate, as a decimal.
    """

    effective_date: date
    maturity: date
    fixed_rate: float
    notional: float = 1_000_000.0
    direction: SwapDirection = SwapDirection.PAYER
    fixed_tenor: Tenor = _ONE_YEAR
    fixed_day_count: DayCount = ACT_360
    floating_tenor: Tenor = _ONE_YEAR
    floating_day_count: DayCount = ACT_360
    floating_spread: float = 0.0

    def __post_init__(self) -> None:
        for name in ("fixed_rate", "floating_spread"):
            if not math.isfinite(getattr(self, name)):
                msg = f"{name} must be finite"
                raise ValueError(msg)
        if not (math.isfinite(self.notional) and self.notional > 0.0):
            msg = f"Notional must be finite and positive, got {self.notional}"
            raise ValueError(msg)
        # Schedules validate effective < maturity and positive tenors.
        Schedule(self.effective_date, self.maturity, self.fixed_tenor)
        Schedule(self.effective_date, self.maturity, self.floating_tenor)

    @cached_property
    def fixed_leg(self) -> tuple[FixedCoupon, ...]:
        """Fixed coupons in payment order."""
        coupons = []
        for period in Schedule(self.effective_date, self.maturity, self.fixed_tenor):
            accrual = self.fixed_day_count.year_fraction(
                period.start, period.end, period.ref_start, period.ref_end
            )
            coupons.append(
                FixedCoupon(
                    payment_date=period.end,
                    amount=self.notional * self.fixed_rate * accrual,
                    accrual_start=period.start,
                    accrual_end=period.end,
                    ref_start=period.ref_start,
                    ref_end=period.ref_end,
                    accrual=accrual,
                )
            )
        return tuple(coupons)

    @cached_property
    def floating_leg(self) -> tuple[OvernightCoupon, ...]:
        """Overnight coupons in payment order."""
        return tuple(
            OvernightCoupon(
                payment_date=period.end,
                nominal=self.notional,
                accrual_start=period.start,
                accrual_end=period.end,
                accrual=self.floating_day_count.year_fraction(period.start, period.end),
                spread=self.floating_spread,
            )
            for period in Schedule(self.effective_date, self.maturity, self.floating_tenor)
        )
