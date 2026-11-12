"""Fixed-rate bullet bond."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from functools import cached_property

from pricer.dates.daycount import ActualActualICMA, DayCount
from pricer.dates.schedule import Schedule
from pricer.dates.tenor import Tenor, TenorUnit
from pricer.instruments.cashflows import Cashflow, FixedCoupon, Redemption


@dataclass(frozen=True)
class FixedRateBond:
    """Fixed-rate bullet bond: periodic fixed coupons, principal repaid at maturity.

    The instrument holds contract terms only. It knows its cash flows and its accrued
    interest, which are contractual, but not its price, which depends on a model and on
    market data (see :mod:`pricer.engines.bond`).

    Dates are unadjusted and coupons are paid on their accrual end date. The schedule is
    generated backwards from maturity, so an irregular period is a short first coupon.

    Attributes:
        issue_date: Start of the first accrual period.
        maturity: Date of the last coupon and of the redemption.
        coupon_rate: Annual coupon rate as a decimal (``0.0425`` for 4.25%).
        frequency: Coupons per year; must divide 12.
        day_count: Coupon accrual convention. ``None`` means ACT/ACT ICMA at the bond
            frequency, the convention of US Treasuries and most government bonds.
        face_amount: Principal, in currency.
    """

    issue_date: date
    maturity: date
    coupon_rate: float
    frequency: int = 2
    day_count: DayCount | None = None
    face_amount: float = 100.0

    def __post_init__(self) -> None:
        if self.frequency <= 0 or 12 % self.frequency != 0:
            msg = f"Coupon frequency must divide 12, got {self.frequency}"
            raise ValueError(msg)
        if not math.isfinite(self.coupon_rate):
            msg = f"Coupon rate must be finite, got {self.coupon_rate}"
            raise ValueError(msg)
        if not (math.isfinite(self.face_amount) and self.face_amount > 0.0):
            msg = f"Face amount must be finite and positive, got {self.face_amount}"
            raise ValueError(msg)
        # Schedule validates issue_date < maturity.
        Schedule(self.issue_date, self.maturity, self.coupon_period)

    @property
    def coupon_period(self) -> Tenor:
        """Length of a regular coupon period."""
        return Tenor(12 // self.frequency, TenorUnit.MONTHS)

    @property
    def accrual_day_count(self) -> DayCount:
        """Effective coupon day count."""
        return self.day_count or ActualActualICMA(self.frequency)

    @cached_property
    def coupons(self) -> tuple[FixedCoupon, ...]:
        """Coupons in payment order."""
        day_count = self.accrual_day_count
        coupons = []
        for period in Schedule(self.issue_date, self.maturity, self.coupon_period):
            accrual = day_count.year_fraction(
                period.start, period.end, period.ref_start, period.ref_end
            )
            coupons.append(
                FixedCoupon(
                    payment_date=period.end,
                    amount=self.face_amount * self.coupon_rate * accrual,
                    accrual_start=period.start,
                    accrual_end=period.end,
                    ref_start=period.ref_start,
                    ref_end=period.ref_end,
                    accrual=accrual,
                )
            )
        return tuple(coupons)

    @cached_property
    def cashflows(self) -> tuple[Cashflow, ...]:
        """All cash flows in payment order: the coupons, then the redemption."""
        return (*self.coupons, Redemption(self.maturity, self.face_amount))

    def remaining_cashflows(self, settlement: date) -> tuple[Cashflow, ...]:
        """Cash flows paid strictly after ``settlement``.

        A flow paid on the settlement date belongs to the seller, who still holds the bond
        at the start of that day (QuantLib's default, ``includeSettlementDateFlows=False``).
        """
        return tuple(cf for cf in self.cashflows if cf.payment_date > settlement)

    def accrued_amount(self, settlement: date) -> float:
        """Coupon accrued since the last coupon date, in currency.

        The buyer pays it to the seller on top of the clean price, because the next coupon
        will be paid in full to the buyer. It is zero on a coupon date and before issue.
        """
        for coupon in self.coupons:
            if coupon.accrual_start < settlement < coupon.accrual_end:
                fraction = self.accrual_day_count.year_fraction(
                    coupon.accrual_start, settlement, coupon.ref_start, coupon.ref_end
                )
                return self.face_amount * self.coupon_rate * fraction
        return 0.0

    def accrued_interest(self, settlement: date) -> float:
        """Accrued interest quoted per 100 of face, as in market price quotes."""
        return 100.0 * self.accrued_amount(settlement) / self.face_amount

    def is_expired(self, settlement: date) -> bool:
        """Whether every cash flow has been paid by ``settlement``."""
        return settlement >= self.maturity
