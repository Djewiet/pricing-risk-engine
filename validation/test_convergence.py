"""Convergence orders of the numerical engines against the Black-Scholes closed form.

A numerical method that agrees with a reference at one setting can still be wrong: what
proves it is the *rate* at which the error vanishes. The CRR tree must converge as
``O(1/N)`` (with an error whose sign follows the parity of ``N``), Monte Carlo as
``O(1/sqrt(n))``. The studies are those of the Model Validation Report.
"""

import pytest

from pricer.engines import black_scholes
from pricer.instruments import OptionType
from validation.report.convergence import (
    REFERENCE_INPUTS,
    REFERENCE_PUT,
    loglog_slope,
    monte_carlo_convergence,
    tree_convergence,
)

EVEN_STEPS = (50, 100, 200, 400, 800, 1600)
PATHS = (1_000, 4_000, 16_000, 64_000)
SEEDS = 50


@pytest.fixture(scope="module")
def reference() -> float:
    """Closed-form price of the reference put."""
    return black_scholes(OptionType.PUT, REFERENCE_PUT.strike, REFERENCE_INPUTS).npv


def test_tree_converges_at_first_order(reference: float) -> None:
    """Log-log slope of the tree error is -1; ``error x N`` is stable."""
    points = tree_convergence(REFERENCE_PUT, REFERENCE_INPUTS, EVEN_STEPS, reference)
    slope = loglog_slope([p.steps for p in points], [p.error for p in points])
    assert -1.05 <= slope <= -0.95
    scaled = [p.error * p.steps for p in points]
    assert max(scaled) - min(scaled) < 0.02 * abs(scaled[-1])


def test_tree_error_sign_follows_parity(reference: float) -> None:
    """At the money, even trees underprice the put and odd trees overprice it."""
    even = tree_convergence(REFERENCE_PUT, REFERENCE_INPUTS, EVEN_STEPS, reference)
    odd = tree_convergence(
        REFERENCE_PUT, REFERENCE_INPUTS, tuple(n + 1 for n in EVEN_STEPS), reference
    )
    assert all(p.error < 0.0 for p in even)
    assert all(p.error > 0.0 for p in odd)


@pytest.mark.parametrize(
    ("antithetic", "control_variate"),
    [(False, False), (True, False), (False, True), (True, True)],
)
def test_monte_carlo_converges_at_half_order(
    reference: float, antithetic: bool, control_variate: bool
) -> None:
    """Standard error decays as ``n**-0.5``; the observed RMSE follows, up to sampling."""
    points = monte_carlo_convergence(
        REFERENCE_PUT,
        REFERENCE_INPUTS,
        PATHS,
        SEEDS,
        antithetic=antithetic,
        control_variate=control_variate,
    )
    paths = [p.paths for p in points]
    assert -0.52 <= loglog_slope(paths, [p.mean_std_error for p in points]) <= -0.48
    assert -0.6 <= loglog_slope(paths, [p.rmse for p in points]) <= -0.4
    for p in points:  # the reported error is the right size: RMSE / s.e. close to 1
        assert 0.7 <= p.rmse / p.mean_std_error <= 1.3
