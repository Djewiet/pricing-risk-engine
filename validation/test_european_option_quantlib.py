"""Benchmark of the Black-Scholes engine and its analytic Greeks against QuantLib.

QuantLib side: ``BlackScholesMertonProcess`` (spot quote, dividend and risk-free curves,
``BlackConstantVol``), ``VanillaOption`` with ``EuropeanExercise`` and
``AnalyticEuropeanEngine``. Every time axis is ACT/365F, as in our model, so ``T``, the zero
rates and the variance ``sigma^2 T`` are the same numbers on both sides.

Two grids:

* flat curves: spot x expiry x rate (including a negative one) x dividend yield x vol x
  call/put, to cover the formula;
* term structures: our bootstrapped Treasury curve handed to QuantLib as a
  ``DiscountCurve``, with expiries between pillars, to check that the model reads the curve
  at the right point and that rho is the sensitivity to the zero rate *to expiry*.
"""

import itertools
from datetime import UTC, date, datetime

import pytest

from pricer.dates import Tenor
from pricer.engines import AnalyticEuropeanEngine
from pricer.instruments import EuropeanOption, OptionType
from pricer.market import (
    FlatForwardCurve,
    FlatVolatility,
    MarketSnapshot,
    ParYieldQuote,
    YieldCurve,
    bootstrap_par_yield_curve,
)
from pricer.models import BlackScholesModel
from validation.quantlib_setup import VALUATION, analytic_option

ql = pytest.importorskip("QuantLib")

STRIKE = 100.0
SPOTS = (80.0, 100.0, 120.0)
EXPIRIES = (date(2025, 12, 12), date(2026, 11, 12), date(2030, 11, 12))
RATES = (0.045, -0.005)
DIVIDENDS = (0.0, 0.02)
VOLS = (0.10, 0.40)
TYPES = (OptionType.CALL, OptionType.PUT)

# Same closed form evaluated in double precision on both sides, with a normal CDF accurate
# to ~1e-16; the residual differences (observed <= 1.1e-13, on theta) come from the order of the
# floating-point operations. Relative 1e-10 leaves three orders of margin, absolute 1e-12
# covers deep out-of-the-money values and Greeks close to zero.
RTOL = 1e-10
ATOL = 1e-12
GREEKS = (
    ("delta", "delta"),
    ("gamma", "gamma"),
    ("vega", "vega"),
    ("theta", "theta"),
    ("rho", "rho"),
    ("dividend_rho", "dividendRho"),
)


def compare(
    option: EuropeanOption, spot: float, rates: YieldCurve, dividends: YieldCurve, vol: float
) -> None:
    market = MarketSnapshot(
        timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
        valuation_date=VALUATION,
        curves={"R": rates, "Q": dividends},
        spots={option.underlying: spot},
        volatilities={option.underlying: FlatVolatility(vol)},
    )
    ours = AnalyticEuropeanEngine(BlackScholesModel("R", "Q")).price(option, market)
    theirs = analytic_option(option, spot, rates, dividends, vol)
    assert ours.npv == pytest.approx(theirs.NPV(), rel=RTOL, abs=ATOL)
    for name, ql_name in GREEKS:
        expected = getattr(theirs, ql_name)()
        assert getattr(ours.greeks, name) == pytest.approx(expected, rel=RTOL, abs=ATOL), name


@pytest.mark.parametrize(
    ("spot", "expiry", "rate", "dividend", "vol", "option_type"),
    list(itertools.product(SPOTS, EXPIRIES, RATES, DIVIDENDS, VOLS, TYPES)),
    ids=str,
)
def test_flat_market_matches_quantlib(
    spot: float, expiry: date, rate: float, dividend: float, vol: float, option_type: OptionType
) -> None:
    option = EuropeanOption("X", STRIKE, expiry, option_type)
    compare(
        option,
        spot,
        FlatForwardCurve(VALUATION, rate),
        FlatForwardCurve(VALUATION, dividend),
        vol,
    )


TREASURY = bootstrap_par_yield_curve(
    VALUATION,
    [
        ParYieldQuote(Tenor.parse(t), r)
        for t, r in {
            "1M": 0.0440, "3M": 0.0430, "6M": 0.0405, "1Y": 0.0385, "2Y": 0.0360,
            "3Y": 0.0355, "5Y": 0.0365, "7Y": 0.0385, "10Y": 0.0420,
        }.items()
    ],
)  # fmt: skip


TERM_STRUCTURE_EXPIRIES = (date(2026, 1, 16), date(2027, 3, 19), date(2032, 12, 17))
TERM_STRUCTURE_STRIKES = (80.0, 100.0, 125.0)


@pytest.mark.parametrize("expiry", TERM_STRUCTURE_EXPIRIES)
@pytest.mark.parametrize("strike", TERM_STRUCTURE_STRIKES)
@pytest.mark.parametrize("option_type", TYPES)
def test_term_structure_matches_quantlib(
    expiry: date, strike: float, option_type: OptionType
) -> None:
    option = EuropeanOption("X", strike, expiry, option_type)
    compare(option, 100.0, TREASURY, FlatForwardCurve(VALUATION, 0.015), 0.25)
