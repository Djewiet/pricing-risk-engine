"""Yield curves.

A yield curve is fully described by its discount function ``P(0, t)``: the price today of
one unit of currency paid at time ``t``. Zero rates and forward rates are derived from it:

* continuously-compounded zero rate: ``z(t) = -ln P(t) / t``
* instantaneous forward rate: ``f(t) = -d ln P(t) / dt``
* simple forward rate between ``t1`` and ``t2``: ``F = (P(t1) / P(t2) - 1) / (t2 - t1)``

Times are year fractions from the curve reference date, measured with the curve's own
day-count convention (ACT/365F by default). This time axis is a curve convention, distinct
from the day counts of the instruments that are priced off the curve.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import Enum, auto
from itertools import pairwise

import numpy as np
import numpy.typing as npt

from pricer.dates.daycount import ACT_365F, DayCount
from pricer.errors import MarketDataError

FloatArray = npt.NDArray[np.float64]


class Compounding(Enum):
    """How an interest rate is compounded."""

    CONTINUOUS = auto()
    """``P = exp(-r t)``"""
    SIMPLE = auto()
    """``P = 1 / (1 + r t)``"""
    COMPOUNDED = auto()
    """``P = (1 + r / m) ** (-m t)`` with ``m`` the compounding frequency."""


def rate_from_discount(
    discount: float,
    t: float,
    compounding: Compounding = Compounding.CONTINUOUS,
    frequency: int = 1,
) -> float:
    """Convert a discount factor into a rate with the given compounding.

    Raises:
        ValueError: If ``t`` is not positive, ``discount`` is not positive or ``frequency``
            is not positive.
    """
    if t <= 0.0:
        msg = f"Rate conversion requires t > 0, got {t}"
        raise ValueError(msg)
    if discount <= 0.0:
        msg = f"Discount factor must be positive, got {discount}"
        raise ValueError(msg)
    match compounding:
        case Compounding.CONTINUOUS:
            return -math.log(discount) / t
        case Compounding.SIMPLE:
            return (1.0 / discount - 1.0) / t
        case Compounding.COMPOUNDED:
            if frequency <= 0:
                msg = f"Compounding frequency must be positive, got {frequency}"
                raise ValueError(msg)
            return float(frequency * (discount ** (-1.0 / (frequency * t)) - 1.0))


def discount_from_rate(
    rate: float,
    t: float,
    compounding: Compounding = Compounding.CONTINUOUS,
    frequency: int = 1,
) -> float:
    """Convert a rate with the given compounding into a discount factor.

    Raises:
        ValueError: If ``frequency`` is not positive for compounded rates, or if a negative
            simple or compounded rate makes the growth factor non-positive.
    """
    match compounding:
        case Compounding.CONTINUOUS:
            return math.exp(-rate * t)
        case Compounding.SIMPLE:
            growth = 1.0 + rate * t
            if growth <= 0.0:
                msg = f"Simple rate {rate} over t={t} gives a non-positive growth factor"
                raise ValueError(msg)
            return 1.0 / growth
        case Compounding.COMPOUNDED:
            if frequency <= 0:
                msg = f"Compounding frequency must be positive, got {frequency}"
                raise ValueError(msg)
            if rate <= -frequency:
                msg = f"Compounded rate {rate} must be greater than -{frequency}"
                raise ValueError(msg)
            return float((1.0 + rate / frequency) ** (-frequency * t))


class YieldCurve(ABC):
    """Abstract discount curve anchored at a reference date.

    Subclasses implement :meth:`discount_factors` only; every other quantity is derived.
    Instances must be immutable.
    """

    @property
    @abstractmethod
    def reference_date(self) -> date:
        """Date at which discount factors equal one."""

    @property
    @abstractmethod
    def day_count(self) -> DayCount:
        """Convention mapping dates to the curve time axis."""

    @abstractmethod
    def discount_factors(self, times: FloatArray) -> FloatArray:
        """Vectorised discount factors ``P(0, t)`` for year fractions ``t >= 0``."""

    def time(self, d: date) -> float:
        """Year fraction from the reference date to ``d`` on the curve time axis."""
        return self.day_count.year_fraction(self.reference_date, d)

    def discount_factor(self, t: float) -> float:
        """Discount factor ``P(0, t)`` for a year fraction ``t >= 0``."""
        return float(self.discount_factors(np.array([t], dtype=np.float64))[0])

    def discount(self, d: date) -> float:
        """Discount factor for a payment on date ``d``."""
        return self.discount_factor(self.time(d))

    def zero_rate(
        self,
        d: date,
        compounding: Compounding = Compounding.CONTINUOUS,
        frequency: int = 1,
    ) -> float:
        """Zero rate to date ``d`` (which must be after the reference date)."""
        t = self.time(d)
        return rate_from_discount(self.discount_factor(t), t, compounding, frequency)

    def forward_rate(
        self,
        start: date,
        end: date,
        compounding: Compounding = Compounding.CONTINUOUS,
        frequency: int = 1,
    ) -> float:
        """Forward rate between ``start`` and ``end`` implied by no-arbitrage.

        Investing from 0 to ``end`` must yield the same as investing from 0 to ``start``
        then rolling forward at the forward rate, so the forward discount factor is
        ``P(start) / P(end)``.
        """
        t1, t2 = self.time(start), self.time(end)
        forward_discount = self.discount_factor(t2) / self.discount_factor(t1)
        return rate_from_discount(forward_discount, t2 - t1, compounding, frequency)


@dataclass(frozen=True, slots=True, eq=False)
class FlatForwardCurve(YieldCurve):
    """Curve with a constant continuously-compounded rate: ``P(t) = exp(-r t)``.

    Attributes:
        reference: Reference date of the curve.
        rate: Continuously-compounded zero rate.
        convention: Day count of the curve time axis.
    """

    reference: date
    rate: float
    convention: DayCount = ACT_365F

    @property
    def reference_date(self) -> date:  # noqa: D102
        return self.reference

    @property
    def day_count(self) -> DayCount:  # noqa: D102
        return self.convention

    def discount_factors(self, times: FloatArray) -> FloatArray:  # noqa: D102
        _check_non_negative(times)
        return np.exp(-self.rate * times)


@dataclass(frozen=True, slots=True, eq=False)
class ZeroSpreadedCurve(YieldCurve):
    """Base curve shifted by a constant continuously-compounded zero spread.

    ``P'(t) = P(t) * exp(-s t)``: every zero rate moves by ``s``, so does every forward rate.
    This is the parallel shift used for curve DV01, and the curve behind a bond z-spread.
    It wraps the base curve instead of copying it, so the shift is exact even between
    pillars, whatever the base interpolation.

    Attributes:
        base: Curve to shift.
        spread: Continuously-compounded spread, as a decimal (``1e-4`` for 1bp).
    """

    base: YieldCurve
    spread: float

    @property
    def reference_date(self) -> date:  # noqa: D102
        return self.base.reference_date

    @property
    def day_count(self) -> DayCount:  # noqa: D102
        return self.base.day_count

    def discount_factors(self, times: FloatArray) -> FloatArray:  # noqa: D102
        return self.base.discount_factors(times) * np.exp(-self.spread * times)


@dataclass(frozen=True, slots=True, eq=False)
class RolledCurve(YieldCurve):
    """Base curve seen from a later reference date, with its forward rates unchanged.

    ``P'(t) = P(delta + t) / P(delta)`` where ``delta`` is the base-curve time of the new
    reference date: tomorrow's curve is today's forward curve. This is the "forwards are
    realised" roll used for bump-and-revalue theta; the alternative, keeping each zero rate
    to a fixed maturity unchanged, is what the analytic Black-Scholes theta assumes. The
    two coincide on a flat curve.

    Attributes:
        base: Curve to roll.
        reference: New reference date, on or after the base reference date.
    """

    base: YieldCurve
    reference: date

    def __post_init__(self) -> None:
        if self.reference < self.base.reference_date:
            msg = (
                f"Cannot roll a curve anchored on {self.base.reference_date} "
                f"back to {self.reference}"
            )
            raise MarketDataError(msg)

    @property
    def reference_date(self) -> date:  # noqa: D102
        return self.reference

    @property
    def day_count(self) -> DayCount:  # noqa: D102
        return self.base.day_count

    @property
    def shift(self) -> float:
        """``delta``: base-curve time of the new reference date."""
        return self.base.time(self.reference)

    def discount_factors(self, times: FloatArray) -> FloatArray:  # noqa: D102
        _check_non_negative(times)
        delta = self.shift
        return self.base.discount_factors(times + delta) / self.base.discount_factor(delta)


@dataclass(frozen=True, slots=True, eq=False)
class DiscountCurve(YieldCurve):
    """Discount curve interpolated log-linearly between pillar discount factors.

    ``ln P(t)`` is piecewise linear in ``t``, which means the instantaneous forward rate is
    piecewise constant between pillars. Consequences:

    * discount factors stay positive and forwards are always finite (no oscillation, unlike
      cubic splines on rates);
    * the curve is *local*: moving one pillar only changes the curve on the two adjacent
      segments, which keeps the bootstrap sequential and the risk (DV01 per pillar) clean;
    * forwards are discontinuous at pillars, which is the price paid for locality.

    Beyond the last pillar the last forward rate is extended (flat-forward extrapolation).

    Attributes:
        reference: Reference date of the curve, where ``P = 1``.
        pillar_dates: Strictly increasing pillar dates, all after ``reference``.
        pillar_discounts: Discount factors at the pillar dates, all positive.
        convention: Day count of the curve time axis.
    """

    reference: date
    pillar_dates: tuple[date, ...]
    pillar_discounts: tuple[float, ...]
    convention: DayCount = ACT_365F
    _times: FloatArray = field(init=False, repr=False)
    _log_discounts: FloatArray = field(init=False, repr=False)

    def __init__(
        self,
        reference: date,
        pillar_dates: Sequence[date],
        pillar_discounts: Sequence[float],
        convention: DayCount = ACT_365F,
    ) -> None:
        if len(pillar_dates) != len(pillar_discounts):
            msg = f"{len(pillar_dates)} pillar dates but {len(pillar_discounts)} discount factors"
            raise MarketDataError(msg)
        if not pillar_dates:
            msg = "A discount curve needs at least one pillar"
            raise MarketDataError(msg)
        if any(d <= reference for d in pillar_dates):
            msg = f"All pillar dates must be after the reference date {reference}"
            raise MarketDataError(msg)
        if any(b <= a for a, b in pairwise(pillar_dates)):
            msg = "Pillar dates must be strictly increasing"
            raise MarketDataError(msg)
        if any(not (math.isfinite(p) and p > 0.0) for p in pillar_discounts):
            msg = "Pillar discount factors must be finite and positive"
            raise MarketDataError(msg)

        times = np.array(
            [0.0, *(convention.year_fraction(reference, d) for d in pillar_dates)],
            dtype=np.float64,
        )
        log_discounts = np.log(np.array([1.0, *pillar_discounts], dtype=np.float64))
        times.setflags(write=False)
        log_discounts.setflags(write=False)

        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "pillar_dates", tuple(pillar_dates))
        object.__setattr__(self, "pillar_discounts", tuple(float(p) for p in pillar_discounts))
        object.__setattr__(self, "convention", convention)
        object.__setattr__(self, "_times", times)
        object.__setattr__(self, "_log_discounts", log_discounts)

    @property
    def reference_date(self) -> date:  # noqa: D102
        return self.reference

    @property
    def day_count(self) -> DayCount:  # noqa: D102
        return self.convention

    @property
    def pillar_times(self) -> FloatArray:
        """Pillar year fractions on the curve time axis (read-only, without ``t = 0``)."""
        return self._times[1:]

    def discount_factors(self, times: FloatArray) -> FloatArray:  # noqa: D102
        _check_non_negative(times)
        knots, log_p = self._times, self._log_discounts
        interpolated = np.interp(times, knots, log_p)
        last_forward = (log_p[-1] - log_p[-2]) / (knots[-1] - knots[-2])
        beyond = times > knots[-1]
        interpolated[beyond] = log_p[-1] + last_forward * (times[beyond] - knots[-1])
        return np.exp(interpolated)


def _check_non_negative(times: FloatArray) -> None:
    if np.any(times < 0.0):
        msg = "Discount factors are only defined for t >= 0"
        raise ValueError(msg)
