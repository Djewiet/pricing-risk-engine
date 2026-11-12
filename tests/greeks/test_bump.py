import math
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from pricer.dates import Tenor
from pricer.engines import AnalyticEuropeanEngine, black_scholes
from pricer.errors import MarketDataError, PricerError
from pricer.greeks import BumpSizes, Greeks, bump_greeks
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

VALUATION = date(2025, 11, 12)
EXPIRY = date(2027, 3, 19)
SLOPED = bootstrap_par_yield_curve(
    VALUATION,
    [
        ParYieldQuote(Tenor.parse(t), r)
        for t, r in {"3M": 0.043, "1Y": 0.0385, "2Y": 0.036, "5Y": 0.0365}.items()
    ],
)


def market(rate_curve: YieldCurve) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
        valuation_date=VALUATION,
        curves={"R": rate_curve, "Q": FlatForwardCurve(VALUATION, 0.013)},
        spots={"SPX": 5000.0},
        volatilities={"SPX": FlatVolatility(0.18)},
    )


FLAT = market(FlatForwardCurve(VALUATION, 0.04))
CURVED = market(SLOPED)
ENGINE = AnalyticEuropeanEngine(BlackScholesModel("R", "Q"))


def greeks_by_bump(
    option: EuropeanOption, m: MarketSnapshot, bumps: BumpSizes | None = None
) -> Greeks:
    return bump_greeks(
        lambda x: ENGINE.price(option, x).npv, m, "SPX", "R", dividend_curve="Q", bumps=bumps
    )


@pytest.mark.parametrize("option_type", list(OptionType))
@pytest.mark.parametrize("strike", [4000.0, 5100.0, 6500.0])
@pytest.mark.parametrize("m", [FLAT, CURVED], ids=["flat", "curve"])
def test_bump_greeks_match_analytic(
    option_type: OptionType, strike: float, m: MarketSnapshot
) -> None:
    # Central differences with the default bumps: O(h^2) truncation (h^2 / 6 times the
    # third derivative for delta). With h = 0.1% of spot this stays below 1e-4 relative; the
    # worst case is the out-of-the-money put, whose delta is small (observed 1.05e-5).
    option = EuropeanOption("SPX", strike, EXPIRY, option_type)
    analytic = ENGINE.price(option, m).greeks
    bumped = greeks_by_bump(option, m)
    for name in ("delta", "gamma", "vega", "rho", "dividend_rho"):
        assert getattr(bumped, name) == pytest.approx(
            getattr(analytic, name), rel=1e-4, abs=1e-9
        ), name


@pytest.mark.parametrize("option_type", list(OptionType))
def test_theta_on_flat_curves_is_the_one_day_value_change(option_type: OptionType) -> None:
    # On flat curves, rolling the curves (forwards realised) also keeps the zero rates to
    # expiry: the bumped theta is exactly 365 (V(T - 1/365) - V(T)), and it differs from the
    # instantaneous analytic theta only by the O(1 day) curvature of V in time.
    option = EuropeanOption("SPX", 5100.0, EXPIRY, option_type)
    inputs = BlackScholesModel("R", "Q").inputs("SPX", EXPIRY, 5100.0, FLAT)
    t = inputs.time_to_expiry

    def value_at(tau: float) -> float:
        rolled = replace(
            inputs,
            time_to_expiry=tau,
            discount_factor=math.exp(-inputs.rate * tau),
            dividend_discount_factor=math.exp(-inputs.dividend_yield * tau),
        )
        return black_scholes(option_type, 5100.0, rolled).npv

    expected = (value_at(t - 1.0 / 365.0) - value_at(t)) * 365.0
    bumped = greeks_by_bump(option, FLAT)
    assert bumped.theta == pytest.approx(expected, rel=1e-10)
    assert bumped.theta == pytest.approx(ENGINE.price(option, FLAT).greeks.theta, rel=1e-3)


def test_theta_on_a_sloped_curve_realises_the_forwards() -> None:
    # With a sloped curve, the roll moves the zero rate to expiry along the curve, so the
    # bumped theta (forwards realised) and the analytic theta (zero rates fixed) differ by
    # the rho times the roll-down of the rate: a convention, not an error.
    option = EuropeanOption("SPX", 5100.0, EXPIRY, OptionType.CALL)
    analytic = ENGINE.price(option, CURVED).greeks
    bumped = greeks_by_bump(option, CURVED)
    rolled = CURVED.roll_forward(1).curve("R")
    roll_down = (rolled.zero_rate(EXPIRY) - SLOPED.zero_rate(EXPIRY)) * 365.0
    # First-order decomposition of the difference.
    expected_gap = analytic.rho * roll_down
    assert bumped.theta - analytic.theta == pytest.approx(expected_gap, rel=0.05)


def test_base_market_is_not_modified() -> None:
    option = EuropeanOption("SPX", 5100.0, EXPIRY, OptionType.PUT)
    before = ENGINE.price(option, CURVED).npv
    greeks_by_bump(option, CURVED)
    assert ENGINE.price(option, CURVED).npv == before
    assert CURVED.spot("SPX") == 5000.0


def test_no_dividend_curve_gives_zero_dividend_rho() -> None:
    option = EuropeanOption("SPX", 5100.0, EXPIRY, OptionType.CALL)
    greeks = bump_greeks(lambda x: ENGINE.price(option, x).npv, FLAT, "SPX", "R")
    assert greeks.dividend_rho == 0.0


def test_custom_bumps_and_their_validation() -> None:
    option = EuropeanOption("SPX", 5100.0, EXPIRY, OptionType.CALL)
    analytic = ENGINE.price(option, FLAT).greeks
    weekly = greeks_by_bump(option, FLAT, bumps=BumpSizes(spot_relative=1e-2, days=7))
    assert weekly.gamma == pytest.approx(analytic.gamma, rel=1e-3)
    assert weekly.theta == pytest.approx(analytic.theta, rel=1e-2)
    for bad in ({"spot_relative": 0.0}, {"volatility": -1e-4}, {"rate": math.nan}, {"days": 0}):
        with pytest.raises(ValueError, match="must be"):
            BumpSizes(**bad)


def test_rolled_theta_is_undefined_for_an_option_expiring_today() -> None:
    # Rolling past expiry makes the value function raise: theta is not defined there.
    option = EuropeanOption("SPX", 5100.0, VALUATION, OptionType.CALL)
    with pytest.raises(PricerError, match="before the valuation date"):
        greeks_by_bump(option, FLAT)


def test_vega_bump_below_zero_volatility_is_rejected() -> None:
    option = EuropeanOption("SPX", 5100.0, EXPIRY, OptionType.CALL)
    zero_vol = FLAT.with_volatility("SPX", FlatVolatility(0.0))
    with pytest.raises(MarketDataError, match="negative"):
        greeks_by_bump(option, zero_vol)
