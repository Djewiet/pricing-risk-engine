"""Black-Scholes implied volatility.

The implied volatility is the ``sigma`` that makes the Black-Scholes price equal to a given
option price. It is how option prices are quoted: a volatility is comparable across
strikes, expiries and underlyings, a price is not.

A solution exists if and only if the price lies strictly inside the no-arbitrage bounds

``max(omega (S Dq - K Dr), 0) < V < S Dq`` (call) or ``K Dr`` (put),

because the price is continuous and strictly increasing in ``sigma`` (vega > 0), from the
discounted forward intrinsic value at ``sigma = 0`` to the upper bound as ``sigma -> inf``.
The root is therefore unique.

Solver: Brent's method on ``sigma``, after doubling the upper end of the bracket until it
contains the root. Newton's method with the analytic vega converges faster near the money
but diverges far from it, where vega vanishes; a bracketing method cannot fail on a valid
price. State of the art for production volume is Jaeckel's "Let's be rational" (machine
precision in two iterations), out of scope here.
"""

from __future__ import annotations

import math
from dataclasses import replace

from scipy.optimize import brentq

from pricer.engines.analytic_european import black_scholes
from pricer.errors import PricerError
from pricer.instruments.option import EuropeanOption, OptionType
from pricer.market.snapshot import MarketSnapshot
from pricer.models.black_scholes import BlackScholesInputs, BlackScholesModel

_INITIAL_UPPER_VOL = 4.0
_MAX_UPPER_VOL = 1_000.0
_VOL_TOLERANCE = 1e-15


def black_scholes_implied_volatility(
    option_type: OptionType, strike: float, price: float, inputs: BlackScholesInputs
) -> float:
    """Volatility that reprices a European option at ``price``.

    The volatility of ``inputs`` is ignored; spot, time and discount factors are used.

    Raises:
        PricerError: If ``price`` is outside the no-arbitrage bounds (no volatility can
            reproduce it), or if the option expires today (the price does not depend on
            the volatility).
    """
    if inputs.time_to_expiry <= 0.0:
        msg = "Implied volatility is undefined for an option expiring today"
        raise PricerError(msg)
    omega = option_type.sign
    spot_pv = inputs.spot * inputs.dividend_discount_factor
    strike_pv = strike * inputs.discount_factor
    lower = max(omega * (spot_pv - strike_pv), 0.0)
    upper = spot_pv if option_type is OptionType.CALL else strike_pv
    if not (math.isfinite(price) and lower < price < upper):
        msg = (
            f"Price {price} is outside the no-arbitrage bounds ({lower}, {upper}): "
            "no implied volatility"
        )
        raise PricerError(msg)

    def residual(sigma: float) -> float:
        return black_scholes(option_type, strike, replace(inputs, volatility=sigma)).npv - price

    high = _INITIAL_UPPER_VOL
    while residual(high) < 0.0:
        high *= 2.0
        if high > _MAX_UPPER_VOL:
            msg = f"Implied volatility of price {price} is above {_MAX_UPPER_VOL}"
            raise PricerError(msg)
    return float(brentq(residual, 0.0, high, xtol=_VOL_TOLERANCE, maxiter=500))


def implied_volatility(
    option: EuropeanOption, price: float, model: BlackScholesModel, market: MarketSnapshot
) -> float:
    """Implied volatility of ``option`` quoted at ``price`` on ``market``.

    The snapshot needs the spot and the curves of ``model``, not a volatility surface.

    Raises:
        PricerError: If the option expired, expires today, or ``price`` is outside the
            no-arbitrage bounds.
    """
    inputs = model.inputs(option.underlying, option.expiry, option.strike, market, 0.0)
    return black_scholes_implied_volatility(option.option_type, option.strike, price, inputs)
