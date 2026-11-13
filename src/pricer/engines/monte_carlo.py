"""Monte Carlo engine for European options under Black-Scholes.

The value is the discounted risk-neutral expectation of the payoff,
``V = Dr E[payoff(S_T)]``, estimated by the average over ``n`` simulated terminal spots.
Under the model, ``S_T`` is sampled *exactly* in one step (no time discretisation error):

``S_T = F exp(-sigma^2 T / 2 + sigma sqrt(T) Z)``,  ``Z ~ N(0, 1)``

so the only error is statistical: the estimator is unbiased with standard error
``stdev(discounted payoff) / sqrt(n)``. Halving the error costs four times the paths.

Two variance reduction techniques, both on by default:

* **Antithetic variates**: each ``Z`` is paired with ``-Z``. The payoff is monotone in
  ``Z``, so the two values are negatively correlated and their average varies less. The
  standard error is computed on the ``n/2`` pair averages, which are the independent draws.
* **Control variate**: the discounted terminal spot ``X = Dr S_T`` has a known mean,
  ``S Dq`` (the forward, discounted). The estimator ``Y - beta (X - S Dq)`` keeps the same
  mean for any ``beta``; the variance-minimising ``beta = Cov(Y, X) / Var(X)`` is estimated
  on the same sample (a bias of order ``1/n``, negligible against the ``1/sqrt(n)`` error).
  The gain is large for in-the-money calls, whose payoff is almost linear in ``S_T``.

Randomness comes only from a :class:`numpy.random.Generator` passed in by the caller. The
engine holds a seed, not a generator, and builds a fresh generator for each valuation: a
valuation is a pure function of (option, market, engine), and bump-and-revalue Greeks reuse
the same random numbers for every bumped market (common random numbers), so the
differences measure the bump, not the noise.

Everything is vectorised: one draw of ``n`` normals, one payoff call, no Python loop over
paths. Memory is about 24 bytes per path.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from pricer.instruments.option import EuropeanOption, FloatArray
from pricer.market.snapshot import MarketSnapshot
from pricer.models.black_scholes import BlackScholesInputs, BlackScholesModel


@dataclass(frozen=True, slots=True)
class MonteCarloValuation:
    """Monte Carlo estimate of an option value, per unit of underlying.

    Attributes:
        npv: Estimated present value.
        std_error: Standard error of the estimate (standard deviation of the estimator).
        paths: Number of simulated terminal spots, antithetic ones included.
        control_beta: Regression coefficient of the control variate; 0 when it is not used.
    """

    npv: float
    std_error: float
    paths: int
    control_beta: float

    def confidence_interval(self, z: float = 1.96) -> tuple[float, float]:
        """Interval ``npv +/- z std_error`` (95% for the default ``z``, by the CLT)."""
        return self.npv - z * self.std_error, self.npv + z * self.std_error


def monte_carlo_european(
    option: EuropeanOption,
    inputs: BlackScholesInputs,
    paths: int,
    rng: np.random.Generator,
    *,
    antithetic: bool = True,
    control_variate: bool = True,
) -> MonteCarloValuation:
    """Estimate the value of a European option by simulating ``S_T``.

    Args:
        option: The option; only its payoff is used.
        inputs: Model quantities (spot, T, discount factors, volatility).
        paths: Number of terminal spots; must be even with antithetic variates.
        rng: Source of randomness; the result is a deterministic function of its state.
        antithetic: Pair each normal draw ``Z`` with ``-Z``.
        control_variate: Use the discounted terminal spot as a control variate.

    Raises:
        ValueError: If ``paths`` is too small, or odd with antithetic variates.
    """
    if paths < 4:
        msg = f"Monte Carlo needs at least 4 paths, got {paths}"
        raise ValueError(msg)
    if antithetic and paths % 2:
        msg = f"Antithetic variates need an even number of paths, got {paths}"
        raise ValueError(msg)

    stdev = inputs.total_volatility
    if antithetic:
        half = rng.standard_normal(paths // 2)
        normals = np.concatenate((half, -half))
    else:
        normals = rng.standard_normal(paths)
    terminal = inputs.forward * np.exp(stdev * normals - 0.5 * stdev * stdev)

    dr = inputs.discount_factor
    payoffs = dr * option.payoff(terminal)
    controls = dr * terminal
    if antithetic:
        # The independent samples are the pair averages.
        payoffs = _pair_average(payoffs)
        controls = _pair_average(controls)

    beta = 0.0
    if control_variate:
        control_mean = inputs.spot * inputs.dividend_discount_factor
        centred = controls - controls.mean()
        variance = float(centred @ centred)
        if variance > 0.0:  # zero volatility: the control is a constant, nothing to learn
            beta = float(centred @ (payoffs - payoffs.mean())) / variance
            payoffs = payoffs - beta * (controls - control_mean)

    n = payoffs.size
    std_error = float(payoffs.std(ddof=1)) / math.sqrt(n)
    return MonteCarloValuation(float(payoffs.mean()), std_error, paths, beta)


def _pair_average(values: FloatArray) -> FloatArray:
    half = values.size // 2
    return 0.5 * (values[:half] + values[half:])


@dataclass(frozen=True, slots=True)
class MonteCarloEuropeanEngine:
    """Values European options by Monte Carlo simulation under Black-Scholes.

    Exists to be checked against the closed form, and as the template of the engines that
    have no closed form (Heston in phase 3, path-dependent payoffs).

    Attributes:
        model: Binds the underlying to the curves of the snapshot.
        paths: Number of simulated terminal spots.
        seed: Seed of the generator built for each valuation.
        antithetic: Use antithetic variates.
        control_variate: Use the discounted terminal spot as a control variate.
    """

    model: BlackScholesModel
    paths: int = 100_000
    seed: int = 20_261_113
    antithetic: bool = True
    control_variate: bool = True

    def price(self, instrument: EuropeanOption, market: MarketSnapshot, /) -> MonteCarloValuation:
        """Estimate the value of ``instrument`` on ``market``.

        Raises:
            PricerError: If the option expired before the valuation date.
            MissingMarketDataError: If the snapshot lacks the spot, a curve or the
                volatility.
        """
        inputs = self.model.inputs(
            instrument.underlying, instrument.expiry, instrument.strike, market
        )
        if inputs.time_to_expiry == 0.0:
            payoff = float(instrument.payoff(np.array([inputs.spot]))[0])
            return MonteCarloValuation(payoff, 0.0, 0, 0.0)
        return monte_carlo_european(
            instrument,
            inputs,
            self.paths,
            np.random.default_rng(self.seed),
            antithetic=self.antithetic,
            control_variate=self.control_variate,
        )
