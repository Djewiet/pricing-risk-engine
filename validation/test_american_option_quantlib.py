"""Benchmark of the CRR binomial tree against QuantLib, for American and European options.

Two independent references:

* ``BinomialVanillaEngine(process, "crr", N)``: QuantLib's CRR tree with the same number of
  steps. QuantLib uses the same up and down moves but a slightly different up probability
  (``p = 1/2 + (r - q - sigma^2/2) sqrt(dt) / (2 sigma)``, a first-order expansion of ours),
  so the two trees differ by O(1/N), not by rounding;
* ``FdBlackScholesVanillaEngine``: a finite-difference PDE solver, a different numerical
  method altogether, for American options where no closed form exists.

Same set-up as the European benchmark: ``BlackScholesMertonProcess``, flat curves,
ACT/365F everywhere.
"""

import itertools
from datetime import UTC, date, datetime
from typing import Any

import pytest

from pricer.engines import BinomialTreeEngine
from pricer.instruments import AmericanOption, EuropeanOption, OptionType, VanillaOption
from pricer.market import FlatForwardCurve, FlatVolatility, MarketSnapshot
from pricer.models import BlackScholesModel
from validation.quantlib_setup import VALUATION, bsm_process, ql_vanilla

ql = pytest.importorskip("QuantLib")

STEPS = 1000
SPOTS = (80.0, 100.0, 120.0)
EXPIRIES = (date(2026, 2, 12), date(2026, 11, 12), date(2028, 11, 12))
RATES = (0.05, 0.0)
DIVIDENDS = (0.0, 0.03)
VOLS = (0.15, 0.40)
TYPES = (OptionType.CALL, OptionType.PUT)
STRIKE = 100.0

# Same N, different up probability: the gap is O(1/N) with a constant growing with sigma
# and T. Observed at N = 1000 (S = 100) over the 288 cases: price <= 1.6e-3 (3Y, 40% vol),
# delta <= 2.3e-5, gamma <= 9.6e-4 relative, theta <= 1.3e-3. Tolerances leave a margin of
# about 2 to 4. The agreement with the closed form and with a PDE solver is tested
# separately, so these tolerances only have to show that the two trees are the same tree.
PRICE_TOL = 3e-3
DELTA_TOL = 1e-4
GAMMA_RTOL = 2e-3
THETA_TOL = 5e-3

# Tree (O(1/N)) against a PDE grid (O(dx^2 + dt^2)): both errors are ~1e-3 at these sizes.
FD_TOL = 5e-3


def market(spot: float, rate: float, dividend: float, vol: float) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
        valuation_date=VALUATION,
        curves={"R": FlatForwardCurve(VALUATION, rate), "Q": FlatForwardCurve(VALUATION, dividend)},
        spots={"X": spot},
        volatilities={"X": FlatVolatility(vol)},
    )


def quantlib_option(
    option: VanillaOption, spot: float, rate: float, dividend: float, vol: float
) -> tuple[Any, Any]:
    process = bsm_process(
        spot, FlatForwardCurve(VALUATION, rate), FlatForwardCurve(VALUATION, dividend), vol
    )
    return ql_vanilla(option), process


CASES = list(itertools.product(SPOTS, EXPIRIES, RATES, DIVIDENDS, VOLS, TYPES))


@pytest.mark.parametrize("style", [AmericanOption, EuropeanOption], ids=["american", "european"])
@pytest.mark.parametrize(
    ("spot", "expiry", "rate", "dividend", "vol", "option_type"), CASES, ids=str
)
def test_tree_matches_quantlib_crr(
    style: type[VanillaOption],
    spot: float,
    expiry: date,
    rate: float,
    dividend: float,
    vol: float,
    option_type: OptionType,
) -> None:
    option = style("X", STRIKE, expiry, option_type)
    ours = BinomialTreeEngine(BlackScholesModel("R", "Q"), STEPS).price(
        option, market(spot, rate, dividend, vol)
    )
    theirs, process = quantlib_option(option, spot, rate, dividend, vol)
    theirs.setPricingEngine(ql.BinomialVanillaEngine(process, "crr", STEPS))
    assert ours.npv == pytest.approx(theirs.NPV(), abs=PRICE_TOL)
    assert ours.delta == pytest.approx(theirs.delta(), abs=DELTA_TOL)
    assert ours.gamma == pytest.approx(theirs.gamma(), rel=GAMMA_RTOL, abs=1e-6)

    payoff = max(option_type.sign * (spot - STRIKE), 0.0)
    if option.early_exercise and ours.npv <= payoff + 1e-9:
        # Exercised today (deep in the money, 7 cases): the value is the payoff, which does
        # not change with time, so the tree theta is 0. QuantLib derives its tree theta from
        # the Black-Scholes PDE, theta = rV - (r - q) S delta - sigma^2 S^2 gamma / 2, which
        # only holds where the option is *not* exercised: with V = omega (S - K),
        # delta = omega, gamma = 0 it gives omega (q S - r K) instead of 0. A documented
        # difference of definition, not a tolerance.
        assert ours.theta == 0.0
    else:
        assert ours.theta == pytest.approx(theirs.theta(), abs=THETA_TOL)


@pytest.mark.parametrize("spot", SPOTS)
@pytest.mark.parametrize("expiry", EXPIRIES[1:])
@pytest.mark.parametrize(("rate", "dividend"), [(0.05, 0.0), (0.01, 0.06)])
@pytest.mark.parametrize("option_type", TYPES)
def test_american_tree_matches_finite_differences(
    spot: float, expiry: date, rate: float, dividend: float, option_type: OptionType
) -> None:
    option = AmericanOption("X", STRIKE, expiry, option_type)
    ours = BinomialTreeEngine(BlackScholesModel("R", "Q"), 2000).price(
        option, market(spot, rate, dividend, 0.25)
    )
    theirs, process = quantlib_option(option, spot, rate, dividend, 0.25)
    theirs.setPricingEngine(ql.FdBlackScholesVanillaEngine(process, 800, 800))
    assert ours.npv == pytest.approx(theirs.NPV(), abs=FD_TOL)
