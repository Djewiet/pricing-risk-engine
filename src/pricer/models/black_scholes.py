"""Black-Scholes(-Merton) model of an equity underlying.

Under the risk-neutral measure the spot follows a geometric Brownian motion

``dS_t = (r_t - q_t) S_t dt + sigma S_t dW_t``

with ``r`` the risk-free rate, ``q`` the continuous dividend yield (or repo/borrow cost)
and ``sigma`` the volatility. ``S_T`` is then lognormal around the forward:

``F(0, T) = S_0 Dq(T) / Dr(T)``,  ``ln S_T ~ N(ln F - sigma^2 T / 2, sigma^2 T)``

where ``Dr(T) = exp(-int_0^T r)`` and ``Dq(T) = exp(-int_0^T q)`` are discount factors read
from two curves of the snapshot. Deterministic term structures of ``r`` and ``q`` only enter
the distribution of ``S_T`` through these two numbers, which is why a European option needs
nothing else from the curves.

The model holds no market data. It is a *binding*: it knows which curves of the snapshot
play the roles of ``r`` and ``q``, and resolves, for one expiry and strike, the handful of
numbers every Black-Scholes engine needs (:class:`BlackScholesInputs`). The analytic, tree
and Monte Carlo engines all consume the same inputs, so they price the same model.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date

from pricer.dates.daycount import ACT_365F, DayCount
from pricer.errors import PricerError
from pricer.market.snapshot import MarketSnapshot


@dataclass(frozen=True, slots=True)
class BlackScholesInputs:
    """Model quantities for one underlying, expiry and strike.

    Attributes:
        spot: Spot price ``S_0``.
        time_to_expiry: ``T``, year fraction on the model time axis.
        discount_factor: ``Dr(T)``, risk-free discount factor to expiry.
        dividend_discount_factor: ``Dq(T)``, dividend discount factor to expiry.
        volatility: Black volatility ``sigma`` for this expiry and strike.
    """

    spot: float
    time_to_expiry: float
    discount_factor: float
    dividend_discount_factor: float
    volatility: float

    @property
    def forward(self) -> float:
        """Forward price ``F = S Dq / Dr``: the strike of a zero-cost forward contract."""
        return self.spot * self.dividend_discount_factor / self.discount_factor

    @property
    def rate(self) -> float:
        """Continuously-compounded zero rate ``r = -ln Dr / T`` (0 at expiry)."""
        return _zero_rate(self.discount_factor, self.time_to_expiry)

    @property
    def dividend_yield(self) -> float:
        """Continuously-compounded dividend yield ``q = -ln Dq / T`` (0 at expiry)."""
        return _zero_rate(self.dividend_discount_factor, self.time_to_expiry)

    @property
    def total_volatility(self) -> float:
        """``sigma sqrt(T)``: standard deviation of ``ln S_T``."""
        return self.volatility * math.sqrt(self.time_to_expiry)


def _zero_rate(discount: float, t: float) -> float:
    return -math.log(discount) / t if t > 0.0 else 0.0


@dataclass(frozen=True, slots=True)
class BlackScholesModel:
    """Lognormal spot with deterministic rates, dividend yield and volatility.

    The spot and the volatility surface are looked up in the snapshot under the
    underlying identifier of the instrument; the curves under the names given here.

    Attributes:
        discount_curve: Risk-free curve ``r``, used to discount and to grow the forward.
        dividend_curve: Dividend-yield curve ``q``; ``None`` for an underlying that pays no
            dividend (``q = 0``).
        day_count: Time axis of the volatility, ``T = day_count(valuation, expiry)``.
            ACT/365F, the equity-option market convention.
    """

    discount_curve: str
    dividend_curve: str | None = None
    day_count: DayCount = ACT_365F

    def inputs(
        self,
        underlying: str,
        expiry: date,
        strike: float,
        market: MarketSnapshot,
        volatility: float | None = None,
    ) -> BlackScholesInputs:
        """Resolve the model quantities for an option on ``underlying``.

        Args:
            underlying: Identifier of the spot and volatility surface in ``market``.
            expiry: Option expiry.
            strike: Option strike, for the volatility lookup.
            market: Market snapshot.
            volatility: Volatility to use instead of the surface of ``market``, which is
                then not read (implied-volatility solving needs no surface).

        Raises:
            PricerError: If ``expiry`` is before the valuation date.
            MissingMarketDataError: If the snapshot lacks the spot, a curve or the
                volatility.
        """
        valuation = market.valuation_date
        if expiry < valuation:
            msg = f"Expiry {expiry} is before the valuation date {valuation}"
            raise PricerError(msg)
        t = self.day_count.year_fraction(valuation, expiry)
        dividend = (
            market.curve(self.dividend_curve).discount(expiry) if self.dividend_curve else 1.0
        )
        return BlackScholesInputs(
            spot=market.spot(underlying),
            time_to_expiry=t,
            discount_factor=market.curve(self.discount_curve).discount(expiry),
            dividend_discount_factor=dividend,
            volatility=(
                market.volatility(underlying).black_vol(t, strike)
                if volatility is None
                else volatility
            ),
        )
