import math
from datetime import UTC, date, datetime

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from pricer.analytics import black_scholes_implied_volatility, implied_volatility
from pricer.engines import AnalyticEuropeanEngine, black_scholes
from pricer.errors import PricerError
from pricer.instruments import EuropeanOption, OptionType
from pricer.market import FlatForwardCurve, FlatVolatility, MarketSnapshot
from pricer.models import BlackScholesInputs, BlackScholesModel

CALL, PUT = OptionType.CALL, OptionType.PUT


def make_inputs(s: float, t: float, r: float, q: float) -> BlackScholesInputs:
    return BlackScholesInputs(s, t, math.exp(-r * t), math.exp(-q * t), math.nan)


@given(
    m=st.floats(0.6, 1.6),
    t=st.floats(0.02, 10.0),
    r=st.floats(-0.02, 0.10),
    q=st.floats(0.0, 0.06),
    sigma=st.floats(0.02, 2.0),
    option_type=st.sampled_from(list(OptionType)),
)
def test_round_trip(
    m: float, t: float, r: float, q: float, sigma: float, option_type: OptionType
) -> None:
    # price(sigma) then implied vol must give sigma back. The achievable accuracy is the
    # price precision divided by vega: skip cases where vega is so small that the price is
    # flat in sigma to double precision (deep out of the money, short expiry).
    inputs = make_inputs(100.0, t, r, q)
    value = black_scholes(
        option_type, 100.0 * m, BlackScholesInputs(100.0, t, *_dfs(inputs), sigma)
    )
    assume(value.greeks.vega > 1e-4)
    implied = black_scholes_implied_volatility(option_type, 100.0 * m, value.npv, inputs)
    assert implied == pytest.approx(sigma, abs=1e-12 * 100.0 / value.greeks.vega + 1e-12)


def _dfs(inputs: BlackScholesInputs) -> tuple[float, float]:
    return inputs.discount_factor, inputs.dividend_discount_factor


def test_call_and_put_have_the_same_implied_volatility() -> None:
    # Put-call parity: if C and P are consistent, they imply the same volatility. A smile is
    # a function of the strike, never of the option type.
    inputs = make_inputs(100.0, 1.5, 0.03, 0.01)
    priced = BlackScholesInputs(100.0, 1.5, *_dfs(inputs), 0.27)
    call = black_scholes(CALL, 110.0, priced).npv
    put = call - (100.0 * inputs.dividend_discount_factor - 110.0 * inputs.discount_factor)
    assert black_scholes_implied_volatility(CALL, 110.0, call, inputs) == pytest.approx(
        black_scholes_implied_volatility(PUT, 110.0, put, inputs), abs=1e-13
    )


def test_very_high_volatility_extends_the_bracket() -> None:
    inputs = make_inputs(100.0, 1.0, 0.0, 0.0)
    price = black_scholes(CALL, 100.0, BlackScholesInputs(100.0, 1.0, 1.0, 1.0, 9.0)).npv
    assert black_scholes_implied_volatility(CALL, 100.0, price, inputs) == pytest.approx(
        9.0, rel=1e-9
    )


@pytest.mark.parametrize(
    ("option_type", "price"),
    [
        (CALL, 0.0),  # at or below intrinsic: zero volatility is not an interior solution
        (CALL, 100.0),  # at the upper bound S Dq: infinite volatility
        (PUT, -1.0),
        (PUT, 200.0),  # above K Dr
        (CALL, math.nan),
    ],
)
def test_prices_outside_the_bounds_have_no_implied_volatility(
    option_type: OptionType, price: float
) -> None:
    with pytest.raises(PricerError, match="no-arbitrage bounds"):
        black_scholes_implied_volatility(
            option_type, 120.0, price, make_inputs(100.0, 1.0, 0.0, 0.0)
        )


def test_in_the_money_price_below_intrinsic_is_rejected() -> None:
    # Forward intrinsic of a 80 call on 100 is 20: a price of 19.5 is an arbitrage.
    with pytest.raises(PricerError, match="no-arbitrage bounds"):
        black_scholes_implied_volatility(CALL, 80.0, 19.5, make_inputs(100.0, 1.0, 0.0, 0.0))


def test_volatility_above_the_cap_is_rejected() -> None:
    # 30 seconds to expiry and an at-the-money price of 99% of spot: sigma sqrt(T) ~ 5.2,
    # so sigma ~ 5,000 (500,000%), beyond the solver cap of 1,000.
    inputs = make_inputs(100.0, 1e-6, 0.0, 0.0)
    with pytest.raises(PricerError, match="above"):
        black_scholes_implied_volatility(CALL, 100.0, 99.0, inputs)


def test_expiring_today_is_rejected() -> None:
    with pytest.raises(PricerError, match="expiring today"):
        black_scholes_implied_volatility(
            CALL, 100.0, 1.0, BlackScholesInputs(100.0, 0.0, 1.0, 1.0, 0.2)
        )


def test_implied_volatility_from_a_market_without_surface() -> None:
    valuation = date(2025, 11, 12)
    curves = {"R": FlatForwardCurve(valuation, 0.04), "Q": FlatForwardCurve(valuation, 0.013)}
    model = BlackScholesModel("R", "Q")
    option = EuropeanOption("SPX", 5100.0, date(2026, 12, 18), PUT)
    with_vol = MarketSnapshot(
        timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
        valuation_date=valuation,
        curves=curves,
        spots={"SPX": 5000.0},
        volatilities={"SPX": FlatVolatility(0.21)},
    )
    price = AnalyticEuropeanEngine(model).price(option, with_vol).npv
    no_vol = MarketSnapshot(
        timestamp=with_vol.timestamp, valuation_date=valuation, curves=curves, spots={"SPX": 5000.0}
    )
    assert implied_volatility(option, price, model, no_vol) == pytest.approx(0.21, abs=1e-13)
