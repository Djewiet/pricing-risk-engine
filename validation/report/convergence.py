"""Convergence studies: binomial tree and Monte Carlo against the closed form.

Pure computations, no QuantLib: the reference is our Black-Scholes formula, itself
benchmarked against QuantLib to 1e-13. Used by the report and by
``validation/test_convergence.py``.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np

from pricer.engines import binomial_tree, black_scholes, monte_carlo_european
from pricer.instruments import EuropeanOption, OptionType, VanillaOption
from pricer.models import BlackScholesInputs


@dataclass(frozen=True, slots=True)
class TreePoint:
    """Tree price error for one number of steps.

    Attributes:
        steps: Number of time steps.
        error: Tree price minus the reference price.
    """

    steps: int
    error: float


@dataclass(frozen=True, slots=True)
class MonteCarloPoint:
    """Monte Carlo error statistics for one number of paths, over many seeds.

    Attributes:
        paths: Number of paths per estimate.
        rmse: Root mean square error of the estimates against the closed form.
        mean_std_error: Average reported standard error.
    """

    paths: int
    rmse: float
    mean_std_error: float


def tree_convergence(
    option: VanillaOption, inputs: BlackScholesInputs, steps: Sequence[int], reference: float
) -> list[TreePoint]:
    """Tree price error against ``reference`` for each number of steps."""
    return [TreePoint(n, binomial_tree(option, inputs, n).npv - reference) for n in steps]


def monte_carlo_convergence(
    option: EuropeanOption,
    inputs: BlackScholesInputs,
    paths: Sequence[int],
    seeds: int,
    *,
    antithetic: bool,
    control_variate: bool,
) -> list[MonteCarloPoint]:
    """RMSE over ``seeds`` independent estimates, for each number of paths."""
    reference = black_scholes(option.option_type, option.strike, inputs).npv
    points = []
    for n in paths:
        errors = np.empty(seeds)
        std_errors = np.empty(seeds)
        for seed in range(seeds):
            value = monte_carlo_european(
                option,
                inputs,
                n,
                np.random.default_rng(seed),
                antithetic=antithetic,
                control_variate=control_variate,
            )
            errors[seed] = value.npv - reference
            std_errors[seed] = value.std_error
        points.append(
            MonteCarloPoint(n, float(np.sqrt(np.mean(errors**2))), float(std_errors.mean()))
        )
    return points


def loglog_slope(x: Sequence[float], y: Sequence[float]) -> float:
    """Least-squares slope of ``log |y|`` against ``log x``: the empirical order of convergence."""
    slope, _ = np.polyfit(np.log(np.asarray(x)), np.log(np.abs(np.asarray(y))), 1)
    return float(slope)


#: The reference case of the convergence studies: one-year at-the-money option.
REFERENCE_INPUTS = BlackScholesInputs(100.0, 1.0, float(np.exp(-0.05)), float(np.exp(-0.02)), 0.25)
#: The date only labels the contract: the time to expiry comes from the inputs.
REFERENCE_PUT = EuropeanOption("X", 100.0, date(2026, 11, 12), OptionType.PUT)
