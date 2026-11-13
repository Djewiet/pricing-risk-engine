"""Cox-Ross-Rubinstein binomial tree for European and American options.

The time to expiry is cut into ``N`` steps of ``dt = T / N``. Over one step the spot moves
up by ``u = exp(sigma sqrt(dt))`` or down by ``d = 1 / u``, so the tree recombines: after
``i`` steps there are ``i + 1`` nodes ``S u^(2j - i)``. The risk-neutral up probability

``p = (exp((r - q) dt) - d) / (u - d)``

makes the discounted spot (with dividends) a martingale on every step, so the tree
reprices the forward exactly; it is the only free parameter once ``u`` and ``d`` are chosen
to match the variance ``sigma^2 dt``. Rates enter as the flat equivalents to expiry,
``r = -ln Dr(T) / T`` and ``q = -ln Dq(T) / T``: exact for a European option, an
approximation of the term structure for an American one (as in QuantLib's tree engines).

Values are computed backwards from the payoff at expiry:

``V_i,j = exp(-r dt) (p V_i+1,j+1 + (1 - p) V_i+1,j)``

and, for an American option, ``V_i,j = max(continuation, payoff(S_i,j))``: at each node the
holder compares exercising now with keeping the option alive. The induction is vectorised
over the nodes of a step (one NumPy operation per step, ``O(N^2)`` work in total).

Delta, gamma and theta come from the first two steps of the tree at no extra cost (Hull's
formulas); vega and rho need a revaluation, see :func:`pricer.greeks.bump_greeks`.

Convergence to Black-Scholes is ``O(1/N)`` and oscillates with the parity of ``N``,
because the strike falls at a different place relative to the terminal nodes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from pricer.errors import PricerError
from pricer.instruments.option import FloatArray, VanillaOption
from pricer.market.snapshot import MarketSnapshot
from pricer.models.black_scholes import BlackScholesInputs, BlackScholesModel


@dataclass(frozen=True, slots=True)
class TreeValuation:
    """Value of an option on a binomial tree, per unit of underlying.

    Attributes:
        npv: Present value at the valuation date.
        delta: ``dV/dS`` from the two nodes after one step.
        gamma: ``d2V/dS2`` from the three nodes after two steps.
        theta: ``dV/dt`` per year, from the middle node after two steps, which has the same
            spot as the root.
        steps: Number of time steps of the tree.
    """

    npv: float
    delta: float
    gamma: float
    theta: float
    steps: int


def binomial_tree(option: VanillaOption, inputs: BlackScholesInputs, steps: int) -> TreeValuation:
    """Value ``option`` on a CRR tree built from the model inputs.

    A free function of the model inputs, like :func:`~pricer.engines.black_scholes`, so the
    convergence studies can vary the number of steps without building snapshots.

    Raises:
        ValueError: If ``steps < 2``.
        PricerError: If the volatility is zero, or too low for the drift over one step
            (``p`` outside ``(0, 1)``: the tree would allow an arbitrage).
    """
    if steps < 2:
        msg = f"A tree needs at least 2 steps for its Greeks, got {steps}"
        raise ValueError(msg)
    s, t = inputs.spot, inputs.time_to_expiry
    if t == 0.0:
        return _expiring_today(option, s)
    sigma = inputs.volatility
    if sigma <= 0.0:
        msg = "A binomial tree needs a positive volatility"
        raise PricerError(msg)

    dt = t / steps
    u = math.exp(sigma * math.sqrt(dt))
    d = 1.0 / u
    growth = math.exp((inputs.rate - inputs.dividend_yield) * dt)
    p = (growth - d) / (u - d)
    if not 0.0 < p < 1.0:
        msg = (
            f"Up probability {p:.6f} outside (0, 1): sigma sqrt(dt) is too small for the "
            f"drift; increase the volatility or the number of steps"
        )
        raise PricerError(msg)
    discount = inputs.discount_factor ** (1.0 / steps)
    weight_up, weight_down = discount * p, discount * (1.0 - p)

    def spots(step: int) -> FloatArray:
        return s * u ** np.arange(-step, step + 1, 2, dtype=np.float64)

    values = option.payoff(spots(steps))
    early_values: dict[int, FloatArray] = {}
    for step in range(steps - 1, -1, -1):
        values = weight_up * values[1:] + weight_down * values[:-1]
        if option.early_exercise:
            values = np.maximum(values, option.payoff(spots(step)))
        if step <= 2:
            early_values[step] = values

    v1, v2 = early_values[1], early_values[2]
    s1, s2 = spots(1), spots(2)
    delta_up = (v2[2] - v2[1]) / (s2[2] - s2[1])
    delta_down = (v2[1] - v2[0]) / (s2[1] - s2[0])
    return TreeValuation(
        npv=float(values[0]),
        delta=float((v1[1] - v1[0]) / (s1[1] - s1[0])),
        gamma=float((delta_up - delta_down) / (0.5 * (s2[2] - s2[0]))),
        theta=float((v2[1] - values[0]) / (2.0 * dt)),
        steps=steps,
    )


def _expiring_today(option: VanillaOption, spot: float) -> TreeValuation:
    value = float(option.payoff(np.array([spot]))[0])
    in_the_money = value > 0.0
    return TreeValuation(
        npv=value,
        delta=float(option.option_type.sign) if in_the_money else 0.0,
        gamma=0.0,
        theta=0.0,
        steps=0,
    )


@dataclass(frozen=True, slots=True)
class BinomialTreeEngine:
    """Values European and American options on a Cox-Ross-Rubinstein tree.

    One engine for both exercise styles: the style is a term of the contract
    (:attr:`~pricer.instruments.option.VanillaOption.early_exercise`), applied at each node.

    Attributes:
        model: Binds the underlying to the curves of the snapshot; the same model as the
            analytic engine, so the two can be compared directly.
        steps: Number of time steps (pricing error ``O(1/steps)``).
    """

    model: BlackScholesModel
    steps: int = 500

    def price(self, instrument: VanillaOption, market: MarketSnapshot, /) -> TreeValuation:
        """Value ``instrument`` on ``market``.

        Raises:
            PricerError: If the option expired, or the tree parameters are invalid.
            MissingMarketDataError: If the snapshot lacks the spot, a curve or the
                volatility.
        """
        inputs = self.model.inputs(
            instrument.underlying, instrument.expiry, instrument.strike, market
        )
        return binomial_tree(instrument, inputs, self.steps)
