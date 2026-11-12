"""Closed-form Black-Scholes engine for European options.

Written on the forward ``F = S Dq / Dr`` (Black 1976), with ``omega = +1`` for a call and
``-1`` for a put:

``V = omega (S Dq N(omega d1) - K Dr N(omega d2))``

``d1 = (ln(F / K) + sigma^2 T / 2) / (sigma sqrt(T))``,  ``d2 = d1 - sigma sqrt(T)``

``N(d2)`` is the risk-neutral probability that a call ends in the money; ``Dq N(d1)`` is
its delta, the number of shares in the replicating portfolio.

Greeks, by differentiating the formula (``phi`` is the standard normal density, ``r`` and
``q`` the zero rates to expiry):

* delta ``= omega Dq N(omega d1)``
* gamma ``= Dq phi(d1) / (S sigma sqrt(T))``, the same for calls and puts
* vega ``= S Dq phi(d1) sqrt(T)``, the same for calls and puts
* theta ``= -S Dq phi(d1) sigma / (2 sqrt(T)) + omega (q S Dq N(omega d1) - r K Dr N(omega d2))``
* rho ``= omega K T Dr N(omega d2)``
* dividend rho ``= -omega S T Dq N(omega d1)``

The identity ``S Dq phi(d1) = K Dr phi(d2)`` is what makes these derivatives so compact: the
terms coming from ``dd1`` and ``dd2`` cancel.

When ``sigma sqrt(T) = 0`` (expiry today, or zero volatility) ``S_T`` is deterministic and
equal to ``F``: the option is worth its discounted forward intrinsic value
``Dr max(omega (F - K), 0)``, and the Greeks are those of that expression (delta is a step,
gamma and vega are zero).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from pricer.greeks.base import Greeks
from pricer.instruments.option import EuropeanOption, OptionType
from pricer.market.snapshot import MarketSnapshot
from pricer.models.black_scholes import BlackScholesInputs, BlackScholesModel

_INV_SQRT_2PI = 1.0 / math.sqrt(2.0 * math.pi)


def norm_cdf(x: float) -> float:
    """Standard normal cumulative distribution function.

    Through ``erfc`` rather than ``1 + erf``, so the left tail keeps full relative
    precision (``N(-10) = 7.6e-24`` instead of 0).
    """
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def norm_pdf(x: float) -> float:
    """Standard normal density."""
    return _INV_SQRT_2PI * math.exp(-0.5 * x * x)


@dataclass(frozen=True, slots=True)
class BlackScholesValuation:
    """Black-Scholes value of a European option, per unit of underlying.

    Attributes:
        npv: Present value at the valuation date.
        forward: Forward price of the underlying to expiry.
        d1: ``(ln(F/K) + sigma^2 T / 2) / (sigma sqrt T)``; ``nan`` when ``sigma sqrt T = 0``.
        d2: ``d1 - sigma sqrt T``; ``nan`` when ``sigma sqrt T = 0``.
        greeks: Analytic sensitivities.
    """

    npv: float
    forward: float
    d1: float
    d2: float
    greeks: Greeks


def black_scholes(
    option_type: OptionType, strike: float, inputs: BlackScholesInputs
) -> BlackScholesValuation:
    """Price and Greeks of a European option in closed form.

    A free function of the model inputs, so that solvers (implied volatility) and other
    engines (control variates) can call it without building snapshots.
    """
    omega = option_type.sign
    s, k, t = inputs.spot, strike, inputs.time_to_expiry
    dr, dq = inputs.discount_factor, inputs.dividend_discount_factor
    r, q = inputs.rate, inputs.dividend_yield
    forward = inputs.forward
    stdev = inputs.total_volatility

    if stdev == 0.0:
        itm = 1.0 if omega * (forward - k) > 0.0 else 0.0
        greeks = Greeks(
            delta=itm * omega * dq,
            gamma=0.0,
            vega=0.0,
            theta=itm * omega * (q * s * dq - r * k * dr),
            rho=itm * omega * k * t * dr,
            dividend_rho=-itm * omega * s * t * dq,
        )
        npv = itm * omega * (s * dq - k * dr)
        return BlackScholesValuation(npv, forward, math.nan, math.nan, greeks)

    d1 = math.log(forward / k) / stdev + 0.5 * stdev
    d2 = d1 - stdev
    n1, n2 = norm_cdf(omega * d1), norm_cdf(omega * d2)
    density = s * dq * norm_pdf(d1)  # = K Dr phi(d2)
    sqrt_t = math.sqrt(t)
    greeks = Greeks(
        delta=omega * dq * n1,
        gamma=density / (s * s * stdev),
        vega=density * sqrt_t,
        theta=-density * inputs.volatility / (2.0 * sqrt_t)
        + omega * (q * s * dq * n1 - r * k * dr * n2),
        rho=omega * k * t * dr * n2,
        dividend_rho=-omega * s * t * dq * n1,
    )
    npv = omega * (s * dq * n1 - k * dr * n2)
    return BlackScholesValuation(npv, forward, d1, d2, greeks)


@dataclass(frozen=True, slots=True)
class AnalyticEuropeanEngine:
    """Values European options with the Black-Scholes closed form.

    Attributes:
        model: Binds the underlying to the curves of the snapshot.
    """

    model: BlackScholesModel

    def price(self, instrument: EuropeanOption, market: MarketSnapshot, /) -> BlackScholesValuation:
        """Value ``instrument`` on ``market``.

        Raises:
            PricerError: If the option expired before the valuation date.
            MissingMarketDataError: If the snapshot lacks the spot, a curve or the
                volatility.
        """
        inputs = self.model.inputs(
            instrument.underlying, instrument.expiry, instrument.strike, market
        )
        return black_scholes(instrument.option_type, instrument.strike, inputs)
