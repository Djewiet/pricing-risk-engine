"""Benchmark of the implied-volatility solver against QuantLib.

Each case prices an option at a known volatility with QuantLib, then inverts the QuantLib
price with both libraries: ``VanillaOption.impliedVolatility`` (Brent, accuracy 1e-12 on the
volatility) and ``pricer.analytics.implied_volatility``. Same set-up as the option
benchmark: ``BlackScholesMertonProcess``, flat curves, ACT/365F everywhere.
"""

import itertools
from datetime import UTC, date, datetime

import pytest

from pricer.analytics import implied_volatility
from pricer.errors import PricerError
from pricer.instruments import EuropeanOption, OptionType
from pricer.market import FlatForwardCurve, MarketSnapshot
from pricer.models import BlackScholesModel
from validation.test_european_option_quantlib import VALUATION, quantlib_option

ql = pytest.importorskip("QuantLib")

STRIKES = (70.0, 95.0, 100.0, 110.0, 140.0)
EXPIRIES = (date(2026, 1, 16), date(2026, 11, 12), date(2030, 11, 12))
VOLS = (0.05, 0.25, 1.2)
TYPES = (OptionType.CALL, OptionType.PUT)
SPOT, RATE, DIVIDEND = 100.0, 0.04, 0.015

# Both solvers stop on the volatility: QuantLib at 1e-12, ours at 1e-15. A price known to
# ~1e-14 relative only fixes sigma to ~1e-14 price / vega, added per case. Where the time
# value is at double-precision noise level (8 of the 90 cases), the test checks repricing.
VOL_ATOL = 1e-10
QL_TODAY = ql.Date(12, 11, 2025)


def _market(rates: FlatForwardCurve, dividends: FlatForwardCurve) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
        valuation_date=VALUATION,
        curves={"R": rates, "Q": dividends},
        spots={"X": SPOT},
    )


@pytest.mark.parametrize(
    ("strike", "expiry", "vol", "option_type"),
    list(itertools.product(STRIKES, EXPIRIES, VOLS, TYPES)),
    ids=str,
)
def test_implied_volatility_matches_quantlib(
    strike: float, expiry: date, vol: float, option_type: OptionType
) -> None:
    option = EuropeanOption("X", strike, expiry, option_type)
    rates = FlatForwardCurve(VALUATION, RATE)
    dividends = FlatForwardCurve(VALUATION, DIVIDEND)
    theirs = quantlib_option(option, SPOT, rates, dividends, vol)
    price = theirs.NPV()
    vega = theirs.vega()
    market = _market(rates, dividends)
    model = BlackScholesModel("R", "Q")
    intrinsic = max(
        option_type.sign * (SPOT * dividends.discount(expiry) - strike * rates.discount(expiry)),
        0.0,
    )
    if price - intrinsic < 1e-10 * SPOT or vega < 1e-8:
        # Low vol far from the money: the time value is at the level of double-precision
        # noise, so the price does not determine sigma. The solver must either reject the
        # price (it equals a bound) or return a sigma that reprices it.
        try:
            ours = implied_volatility(option, price, model, market)
        except PricerError:
            return
        repriced = quantlib_option(option, SPOT, rates, dividends, ours).NPV()
        assert repriced == pytest.approx(price, abs=1e-14 * SPOT)
        return

    ours = implied_volatility(option, price, model, market)
    process = ql.BlackScholesMertonProcess(
        ql.QuoteHandle(ql.SimpleQuote(SPOT)),
        ql.YieldTermStructureHandle(ql.FlatForward(QL_TODAY, DIVIDEND, ql.Actual365Fixed())),
        ql.YieldTermStructureHandle(ql.FlatForward(QL_TODAY, RATE, ql.Actual365Fixed())),
        ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(QL_TODAY, ql.NullCalendar(), 0.3, ql.Actual365Fixed())
        ),
    )
    implied_ql = theirs.impliedVolatility(price, process, 1e-12, 500, 1e-7, 10.0)
    tolerance = VOL_ATOL + 1e-14 * max(price, 1.0) / vega
    assert ours == pytest.approx(implied_ql, abs=tolerance)
    assert ours == pytest.approx(vol, abs=tolerance)
