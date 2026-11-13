"""Statistical validation of the Monte Carlo engine.

A Monte Carlo price is a random variable, so it cannot be compared with a reference to a
fixed tolerance. What can be checked is that its *error model* is right: over many
independent seeds, the standardised errors ``z = (estimate - reference) / std_error``
must look like a standard normal, so that the reported confidence intervals have their
nominal coverage. A biased estimator shifts the mean of ``z``; an underestimated standard
error inflates its variance and the coverage drops below 95%.

The reference is QuantLib's ``AnalyticEuropeanEngine``, independent of our closed form.
"""

import itertools
from datetime import date

import numpy as np
import pytest

from pricer.engines import monte_carlo_european
from pricer.instruments import EuropeanOption, OptionType
from pricer.market import FlatForwardCurve
from pricer.models import BlackScholesInputs
from validation.quantlib_setup import VALUATION, analytic_option

ql = pytest.importorskip("QuantLib")

EXPIRY = date(2026, 11, 12)  # 365 days: T = 1
SPOT, RATE, DIVIDEND, VOL = 100.0, 0.05, 0.02, 0.25
SEEDS = 400
PATHS = 2_000

# With 400 seeds: the coverage of a 95% interval has a sampling standard deviation of
# sqrt(0.95 * 0.05 / 400) = 1.1%, so [0.917, 0.983] is a +/- 3 sigma band; the mean of z
# has standard deviation 1/sqrt(400) = 0.05 (band +/- 0.2) and its variance ~0.07
# (band [0.75, 1.3]). Seeds are fixed, so the test is deterministic.
COVERAGE_BAND = (0.917, 0.983)
MEAN_BAND = 0.2
VARIANCE_BAND = (0.75, 1.3)


@pytest.mark.parametrize(
    ("strike", "option_type", "antithetic", "control_variate"),
    list(itertools.product((80.0, 100.0, 130.0), tuple(OptionType), (False, True), (False, True))),
    ids=str,
)
def test_confidence_intervals_have_nominal_coverage(
    strike: float, option_type: OptionType, antithetic: bool, control_variate: bool
) -> None:
    option = EuropeanOption("X", strike, EXPIRY, option_type)
    reference = analytic_option(
        option,
        SPOT,
        FlatForwardCurve(VALUATION, RATE),
        FlatForwardCurve(VALUATION, DIVIDEND),
        VOL,
    ).NPV()
    inputs = BlackScholesInputs(SPOT, 1.0, np.exp(-RATE), np.exp(-DIVIDEND), VOL)

    z = np.empty(SEEDS)
    for seed in range(SEEDS):
        value = monte_carlo_european(
            option,
            inputs,
            PATHS,
            np.random.default_rng(seed),
            antithetic=antithetic,
            control_variate=control_variate,
        )
        z[seed] = (value.npv - reference) / value.std_error

    coverage = float(np.mean(np.abs(z) < 1.96))
    assert COVERAGE_BAND[0] <= coverage <= COVERAGE_BAND[1]
    assert abs(float(z.mean())) < MEAN_BAND
    assert VARIANCE_BAND[0] <= float(z.var(ddof=1)) <= VARIANCE_BAND[1]
