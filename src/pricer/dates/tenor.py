"""Tenors (``"6M"``, ``"10Y"``...) and calendar-month date arithmetic.

Dates are never business-day adjusted in this module: date rolling depends on a holiday
calendar, which is an explicit choice made by the caller, not a hidden default.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum

_TENOR_PATTERN = re.compile(r"^\s*(\d+)\s*([DWMY])\s*$", re.IGNORECASE)


class TenorUnit(StrEnum):
    """Unit of a :class:`Tenor`."""

    DAYS = "D"
    WEEKS = "W"
    MONTHS = "M"
    YEARS = "Y"


def add_months(start: date, months: int) -> date:
    """Shift a date by a whole number of calendar months.

    The day of month is clamped to the length of the target month, so that
    ``add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)``. No end-of-month rolling is
    applied (``2025-02-28 + 1M == 2025-03-28``), matching QuantLib with ``endOfMonth=False``.

    Args:
        start: Date to shift.
        months: Number of months, possibly negative.

    Returns:
        The shifted date.
    """
    month_index = start.year * 12 + (start.month - 1) + months
    year, month = divmod(month_index, 12)
    month += 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


@dataclass(frozen=True, slots=True)
class Tenor:
    """A length of time expressed in calendar units, e.g. ``Tenor(6, TenorUnit.MONTHS)``."""

    length: int
    unit: TenorUnit

    def __post_init__(self) -> None:
        if self.length < 0:
            msg = f"Tenor length must be non-negative, got {self.length}"
            raise ValueError(msg)

    @classmethod
    def parse(cls, text: str) -> Tenor:
        """Parse a tenor string such as ``"3M"``, ``"10Y"`` or ``"6W"`` (case-insensitive).

        Raises:
            ValueError: If the string is not a valid tenor.
        """
        match = _TENOR_PATTERN.match(text)
        if match is None:
            msg = f"Invalid tenor: {text!r}"
            raise ValueError(msg)
        return cls(int(match.group(1)), TenorUnit(match.group(2).upper()))

    def advance(self, start: date, times: int = 1) -> date:
        """Return ``start`` shifted by ``times`` tenors (negative ``times`` goes backwards).

        Shifting by ``n`` tenors in one step (rather than iterating) avoids day-of-month
        drift: stepping ``31-Aug-2025`` back twice by 6M gives ``28-Feb-2025`` then
        ``28-Aug-2024``, whereas ``advance(..., times=-2)`` gives ``31-Aug-2024``.
        """
        n = self.length * times
        match self.unit:
            case TenorUnit.DAYS:
                return start + timedelta(days=n)
            case TenorUnit.WEEKS:
                return start + timedelta(weeks=n)
            case TenorUnit.MONTHS:
                return add_months(start, n)
            case TenorUnit.YEARS:
                return add_months(start, 12 * n)

    def __str__(self) -> str:
        return f"{self.length}{self.unit.value}"
