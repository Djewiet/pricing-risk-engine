"""Day-count conventions: how a calendar period is turned into a year fraction.

A day count is part of the contract (coupons, deposits) or of a curve's time axis, so it is
always passed explicitly. All conventions are stateless, immutable objects that satisfy the
:class:`DayCount` protocol, so a new convention never requires changing calling code.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable


@runtime_checkable
class DayCount(Protocol):
    """A day-count convention."""

    @property
    def name(self) -> str:
        """Market name of the convention, e.g. ``"ACT/365F"``."""
        ...

    def year_fraction(
        self,
        start: date,
        end: date,
        ref_start: date | None = None,
        ref_end: date | None = None,
    ) -> float:
        """Year fraction between ``start`` and ``end``.

        Args:
            start: Start of the accrual period.
            end: End of the accrual period.
            ref_start: Start of the reference (regular coupon) period, used by ICMA only.
            ref_end: End of the reference (regular coupon) period, used by ICMA only.
        """
        ...


@dataclass(frozen=True, slots=True)
class Actual360:
    """ACT/360: actual days over 360. Money-market convention (EUR, USD deposits)."""

    @property
    def name(self) -> str:  # noqa: D102
        return "ACT/360"

    def year_fraction(  # noqa: D102
        self,
        start: date,
        end: date,
        ref_start: date | None = None,
        ref_end: date | None = None,
    ) -> float:
        return (end - start).days / 360.0


@dataclass(frozen=True, slots=True)
class Actual365Fixed:
    """ACT/365F: actual days over 365, ignoring leap years. Default curve time axis."""

    @property
    def name(self) -> str:  # noqa: D102
        return "ACT/365F"

    def year_fraction(  # noqa: D102
        self,
        start: date,
        end: date,
        ref_start: date | None = None,
        ref_end: date | None = None,
    ) -> float:
        return (end - start).days / 365.0


@dataclass(frozen=True, slots=True)
class Thirty360BondBasis:
    """30/360 Bond Basis (ISDA 2006 section 4.16(f)), used by USD corporate bonds."""

    @property
    def name(self) -> str:  # noqa: D102
        return "30/360"

    def year_fraction(  # noqa: D102
        self,
        start: date,
        end: date,
        ref_start: date | None = None,
        ref_end: date | None = None,
    ) -> float:
        d1 = min(start.day, 30)
        d2 = end.day
        if d2 == 31 and d1 == 30:
            d2 = 30
        days = 360 * (end.year - start.year) + 30 * (end.month - start.month) + (d2 - d1)
        return days / 360.0


@dataclass(frozen=True, slots=True)
class ActualActualISDA:
    """ACT/ACT ISDA: days in leap years over 366 plus days in other years over 365."""

    @property
    def name(self) -> str:  # noqa: D102
        return "ACT/ACT ISDA"

    def year_fraction(  # noqa: D102
        self,
        start: date,
        end: date,
        ref_start: date | None = None,
        ref_end: date | None = None,
    ) -> float:
        if end < start:
            return -self.year_fraction(end, start)
        if start.year == end.year:
            return (end - start).days / _days_in_year(start.year)
        first = (date(start.year + 1, 1, 1) - start).days / _days_in_year(start.year)
        last = (end - date(end.year, 1, 1)).days / _days_in_year(end.year)
        return first + (end.year - start.year - 1) + last


@dataclass(frozen=True, slots=True)
class ActualActualICMA:
    """ACT/ACT ICMA: actual days over the actual length of the coupon period.

    A regular coupon period accrues exactly ``1 / frequency`` regardless of its length in
    days, which is why a semi-annual par bond pays exactly ``rate / 2`` per regular coupon.
    This is the convention of US Treasuries and most government bonds.

    Only accrual periods contained in a single reference period are supported (regular
    periods and short stubs). Long stubs would need several reference periods.

    Attributes:
        frequency: Number of regular coupons per year.
    """

    frequency: int

    def __post_init__(self) -> None:
        if self.frequency <= 0:
            msg = f"Coupon frequency must be positive, got {self.frequency}"
            raise ValueError(msg)

    @property
    def name(self) -> str:  # noqa: D102
        return "ACT/ACT ICMA"

    def year_fraction(  # noqa: D102
        self,
        start: date,
        end: date,
        ref_start: date | None = None,
        ref_end: date | None = None,
    ) -> float:
        if start == end:
            return 0.0
        if ref_start is None or ref_end is None:
            msg = "ACT/ACT ICMA requires the reference coupon period"
            raise ValueError(msg)
        if not ref_start <= start < end <= ref_end:
            msg = (
                f"Accrual period [{start}, {end}] must lie within the reference period "
                f"[{ref_start}, {ref_end}] (long stubs are not supported)"
            )
            raise ValueError(msg)
        return (end - start).days / ((ref_end - ref_start).days * self.frequency)


def _days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


ACT_360 = Actual360()
ACT_365F = Actual365Fixed()
THIRTY_360 = Thirty360BondBasis()
ACT_ACT_ISDA = ActualActualISDA()
