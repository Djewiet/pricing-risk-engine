"""Coupon schedule generation."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from pricer.dates.tenor import Tenor


@dataclass(frozen=True, slots=True)
class Period:
    """One accrual period of a schedule.

    Attributes:
        start: Accrual start date.
        end: Accrual end date, which is also the payment date (no payment lag).
        ref_start: Start of the regular period this one belongs to. Differs from ``start``
            only for a short front stub.
        ref_end: End of the regular period this one belongs to.
    """

    start: date
    end: date
    ref_start: date
    ref_end: date

    @property
    def is_regular(self) -> bool:
        """Whether the period has the full regular length."""
        return self.start == self.ref_start and self.end == self.ref_end


@dataclass(frozen=True, slots=True)
class Schedule:
    """Unadjusted schedule generated backwards from maturity, with a short front stub.

    Backward generation is the market standard for bonds and swaps: coupon dates are anchored
    on the maturity date, and any irregular period falls at the start.

    Attributes:
        effective: Start date of the first accrual period.
        maturity: End date of the last accrual period.
        tenor: Length of a regular period, e.g. 6M for a semi-annual bond.
    """

    effective: date
    maturity: date
    tenor: Tenor

    def __post_init__(self) -> None:
        if self.maturity <= self.effective:
            msg = f"Maturity {self.maturity} must be after effective date {self.effective}"
            raise ValueError(msg)
        if self.tenor.advance(self.maturity, -1) >= self.maturity:
            msg = f"Schedule tenor must be positive, got {self.tenor}"
            raise ValueError(msg)

    @property
    def dates(self) -> tuple[date, ...]:
        """All schedule dates, from effective to maturity."""
        dates = [self.maturity]
        n = 1
        while (d := self.tenor.advance(self.maturity, -n)) > self.effective:
            dates.append(d)
            n += 1
        dates.append(self.effective)
        return tuple(reversed(dates))

    @property
    def periods(self) -> tuple[Period, ...]:
        """Accrual periods with their reference periods (for ACT/ACT ICMA)."""
        dates = self.dates
        periods = [Period(start, end, start, end) for start, end in pairwise(dates[1:])]
        first_end = dates[1]
        # The first period is regular when the date generated from maturity lands exactly
        # on the effective date. Otherwise it is a short stub, whose reference period is
        # one tenor back from its end date (QuantLib FixedRateLeg convention).
        first_is_regular = self.tenor.advance(self.maturity, -(len(dates) - 1)) == self.effective
        ref_start = self.effective if first_is_regular else self.tenor.advance(first_end, -1)
        periods.insert(0, Period(dates[0], first_end, ref_start, first_end))
        return tuple(periods)

    def __iter__(self) -> Iterator[Period]:
        return iter(self.periods)
