"""Black volatility term structures.

Only a flat volatility is provided in phase 1. Pricing code depends on the
:class:`VolatilitySurface` protocol, so a term structure or a smile can be added later
without touching any engine.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pricer.errors import MarketDataError


@runtime_checkable
class VolatilitySurface(Protocol):
    """Black (lognormal) implied volatility as a function of expiry and strike."""

    def black_vol(self, t: float, strike: float) -> float:
        """Annualised Black volatility for expiry ``t`` (year fraction) and ``strike``."""
        ...


@dataclass(frozen=True, slots=True)
class FlatVolatility:
    """Volatility that is constant across expiries and strikes.

    Attributes:
        sigma: Annualised volatility as a decimal (``0.2`` for 20%).
    """

    sigma: float

    def __post_init__(self) -> None:
        if not (math.isfinite(self.sigma) and self.sigma >= 0.0):
            msg = f"Volatility must be finite and non-negative, got {self.sigma}"
            raise MarketDataError(msg)

    def black_vol(self, t: float, strike: float) -> float:  # noqa: D102
        return self.sigma


@dataclass(frozen=True, slots=True)
class ShiftedVolatility:
    """Volatility surface shifted in parallel: ``sigma'(t, K) = sigma(t, K) + shift``.

    Wraps the base surface instead of copying it, like
    :class:`~pricer.market.curves.ZeroSpreadedCurve` for curves: the bump used for vega by
    bump-and-revalue, whatever the shape of the surface.

    Attributes:
        base: Surface to shift.
        shift: Absolute volatility shift (``0.01`` for one vol point).
    """

    base: VolatilitySurface
    shift: float

    def black_vol(self, t: float, strike: float) -> float:
        """Shifted volatility.

        Raises:
            MarketDataError: If the shift makes the volatility negative.
        """
        sigma = self.base.black_vol(t, strike) + self.shift
        if sigma < 0.0:
            msg = f"Volatility shift {self.shift} makes the volatility negative ({sigma})"
            raise MarketDataError(msg)
        return sigma
