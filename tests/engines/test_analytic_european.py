import math
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pricer.dates import Tenor
from pricer.engines import (
    AnalyticEuropeanEngine,
    BlackScholesValuation,
    PricingEngine,
    black_scholes,
)
from pricer.engines.analytic_european import norm_cdf, norm_pdf
from pricer.errors import PricerError
from pricer.greeks import Greeks
from pricer.instruments import EuropeanOption, OptionType
from pricer.market import (
    FlatForwardCurve,
    FlatVolatility,
    MarketSnapshot,
    ParYieldQuote,
    ZeroSpreadedCurve,
    bootstrap_par_yield_curve,
)
from pricer.models import BlackScholesInputs, BlackScholesModel

CALL, PUT = OptionType.CALL, OptionType.PUT


def make_inputs(s: float, t: float, r: float, q: float, sigma: float) -> BlackScholesInputs:
    return BlackScholesInputs(s, t, math.exp(-r * t), math.exp(-q * t), sigma)


def price(
    option_type: OptionType, k: float, s: float, t: float, r: float, q: float, v: float
) -> float:
    return black_scholes(option_type, k, make_inputs(s, t, r, q, v)).npv


# --------------------------------------------------------------------------- closed forms


def test_textbook_example() -> None:
    # Hull, Options, Futures and Other Derivatives, example 15.6: S=42, K=40, r=10%,
    # sigma=20%, T=0.5 gives c = 4.76 and p = 0.81 (rounded to the cent in the book).
    inputs = make_inputs(42.0, 0.5, 0.10, 0.0, 0.20)
    call = black_scholes(CALL, 40.0, inputs)
    assert call.npv == pytest.approx(4.76, abs=5e-3)
    assert black_scholes(PUT, 40.0, inputs).npv == pytest.approx(0.81, abs=5e-3)
    assert call.d1 == pytest.approx(0.7693, abs=1e-4)
    assert call.d2 == pytest.approx(0.6278, abs=1e-4)


@pytest.mark.parametrize("option_type", [CALL, PUT])
@pytest.mark.parametrize("sigma", [0.05, 0.2, 0.8])
def test_at_the_money_forward_closed_form(option_type: OptionType, sigma: float) -> None:
    # K = F gives d1 = -d2 = sigma sqrt(T) / 2, so V = Dr F (2 N(sigma sqrt(T) / 2) - 1)
    # = Dr F erf(sigma sqrt(T) / (2 sqrt 2)), for calls and puts alike.
    t = 2.0
    inputs = make_inputs(100.0, t, 0.03, 0.01, sigma)
    expected = (
        inputs.discount_factor
        * inputs.forward
        * math.erf(sigma * math.sqrt(t) / (2.0 * math.sqrt(2.0)))
    )
    value = black_scholes(option_type, inputs.forward, inputs)
    assert value.npv == pytest.approx(expected, rel=1e-14)
    assert value.d1 == pytest.approx(-value.d2, rel=1e-14)


def test_norm_cdf_keeps_tail_precision() -> None:
    assert norm_cdf(-10.0) == pytest.approx(7.619853024160527e-24, rel=1e-14)
    assert norm_cdf(0.0) == 0.5
    assert norm_cdf(1.959963984540054) == pytest.approx(0.975, rel=1e-15)
    assert norm_pdf(0.0) == pytest.approx(1.0 / math.sqrt(2.0 * math.pi), rel=1e-16)


def test_deep_out_of_the_money_price_is_positive() -> None:
    # 1 + erf would round the probability to zero; erfc keeps a positive price.
    assert 0.0 < price(CALL, 400.0, 100.0, 0.25, 0.03, 0.0, 0.2) < 1e-20


# --------------------------------------------------------------------------- degenerate cases


@pytest.mark.parametrize(("option_type", "itm"), [(CALL, 1.0), (PUT, 0.0)])
def test_zero_volatility_is_discounted_forward_intrinsic(
    option_type: OptionType, itm: float
) -> None:
    s, t, r, q, k = 100.0, 1.5, 0.05, 0.01, 95.0
    inputs = make_inputs(s, t, r, q, 0.0)
    value = black_scholes(option_type, k, inputs)
    dr, dq = inputs.discount_factor, inputs.dividend_discount_factor
    assert value.npv == pytest.approx(itm * (s * dq - k * dr), rel=1e-15)
    assert math.isnan(value.d1)
    assert math.isnan(value.d2)
    # The degenerate Greeks are the limit of the general formula as sigma -> 0.
    limit = black_scholes(option_type, k, replace(inputs, volatility=1e-6)).greeks
    for name in ("delta", "theta", "rho", "dividend_rho"):
        assert getattr(value.greeks, name) == pytest.approx(getattr(limit, name), abs=1e-12)
    assert value.greeks.gamma == 0.0
    assert value.greeks.vega == 0.0


@pytest.mark.parametrize(("option_type", "spot"), [(CALL, 110.0), (CALL, 90.0), (PUT, 90.0)])
def test_option_expiring_today_is_worth_its_payoff(option_type: OptionType, spot: float) -> None:
    value = black_scholes(option_type, 100.0, BlackScholesInputs(spot, 0.0, 1.0, 1.0, 0.3))
    itm = option_type.sign * (spot - 100.0) > 0.0
    assert value.npv == pytest.approx(max(option_type.sign * (spot - 100.0), 0.0), abs=1e-15)
    assert value.greeks.delta == (option_type.sign if itm else 0.0)
    assert value.greeks.gamma == 0.0
    assert value.greeks.rho == 0.0


# --------------------------------------------------------------------------- arbitrage properties

spots = st.floats(1.0, 1_000.0)
moneyness = st.floats(0.5, 2.0)
times = st.floats(1.0 / 365.0, 10.0)
rates = st.floats(-0.02, 0.10)
yields = st.floats(0.0, 0.06)
vols = st.floats(0.01, 1.0)


@given(s=spots, m=moneyness, t=times, r=rates, q=yields, v=vols)
def test_put_call_parity(s: float, m: float, t: float, r: float, q: float, v: float) -> None:
    # C - P is the value of a forward struck at K: S Dq - K Dr, whatever the model.
    k = s * m
    inputs = make_inputs(s, t, r, q, v)
    call, put = black_scholes(CALL, k, inputs), black_scholes(PUT, k, inputs)
    forward_value = s * inputs.dividend_discount_factor - k * inputs.discount_factor
    assert call.npv - put.npv == pytest.approx(forward_value, abs=1e-12 * s)
    # Greeks of a forward: delta Dq, no gamma or vega.
    assert call.greeks.delta - put.greeks.delta == pytest.approx(
        inputs.dividend_discount_factor, abs=1e-14
    )
    assert call.greeks.gamma == pytest.approx(put.greeks.gamma, rel=1e-12, abs=1e-300)
    assert call.greeks.vega == pytest.approx(put.greeks.vega, rel=1e-12, abs=1e-300)


@given(s=spots, m=moneyness, t=times, r=rates, q=yields, v=vols)
def test_no_arbitrage_bounds(s: float, m: float, t: float, r: float, q: float, v: float) -> None:
    k = s * m
    inputs = make_inputs(s, t, r, q, v)
    dr, dq = inputs.discount_factor, inputs.dividend_discount_factor
    call, put = black_scholes(CALL, k, inputs), black_scholes(PUT, k, inputs)
    eps = 1e-12 * s
    # Lower bound: the option is worth at least the forward it can replicate; upper bound:
    # a call is worth less than the share, a put less than the discounted strike.
    assert max(s * dq - k * dr, 0.0) - eps <= call.npv <= s * dq + eps
    assert max(k * dr - s * dq, 0.0) - eps <= put.npv <= k * dr + eps
    assert -eps <= call.greeks.delta <= dq + eps
    assert -dq - eps <= put.greeks.delta <= eps
    assert call.greeks.gamma >= 0.0
    assert call.greeks.vega >= 0.0


@given(s=spots, m=st.floats(0.6, 1.6), t=times, r=rates, q=yields, v=vols)
def test_call_is_decreasing_and_convex_in_strike(
    s: float, m: float, t: float, r: float, q: float, v: float
) -> None:
    # A call spread and a butterfly have non-negative payoffs, so non-negative prices.
    k, h = s * m, 0.05 * s
    lo, mid, hi = (price(CALL, x, s, t, r, q, v) for x in (k - h, k, k + h))
    eps = 1e-11 * s
    assert lo >= mid - eps
    assert mid >= hi - eps
    assert lo - 2.0 * mid + hi >= -eps


@given(s=spots, m=moneyness, t=times, r=rates, q=yields, v=vols)
def test_black_scholes_pde(s: float, m: float, t: float, r: float, q: float, v: float) -> None:
    # Theta, delta and gamma are tied by the PDE that every derivative on S must satisfy:
    # theta + (r - q) S delta + sigma^2 S^2 gamma / 2 - r V = 0.
    for option_type in (CALL, PUT):
        value = black_scholes(option_type, s * m, make_inputs(s, t, r, q, v))
        g = value.greeks
        residual = g.theta + (r - q) * s * g.delta + 0.5 * v * v * s * s * g.gamma - r * value.npv
        assert residual == pytest.approx(0.0, abs=1e-11 * s / math.sqrt(t))


# --------------------------------------------------------------------------- finite differences

FD_CASES = [
    (CALL, 100.0, 100.0, 1.0, 0.04, 0.01, 0.2),
    (PUT, 100.0, 100.0, 1.0, 0.04, 0.01, 0.2),
    (CALL, 120.0, 100.0, 0.1, 0.05, 0.0, 0.35),
    (PUT, 80.0, 100.0, 5.0, -0.005, 0.03, 0.15),
    (PUT, 100.0, 130.0, 2.0, 0.02, 0.02, 0.6),
]


def central(f: Callable[[float], float], x: float, h: float) -> float:
    return (f(x + h) - f(x - h)) / (2.0 * h)


@pytest.mark.parametrize(("option_type", "s", "k", "t", "r", "q", "v"), FD_CASES)
def test_greeks_match_finite_differences(
    option_type: OptionType, s: float, k: float, t: float, r: float, q: float, v: float
) -> None:
    # Central differences: truncation error O(h^2), so relative 1e-6 is a loose bound for
    # steps of 1e-4 relative; the second difference for gamma loses ~1e-16 V / h^2 to
    # round-off, still below 1e-8 relative here.
    g = black_scholes(option_type, k, make_inputs(s, t, r, q, v)).greeks

    def f(s: float = s, t: float = t, r: float = r, q: float = q, v: float = v) -> float:
        return price(option_type, k, s, t, r, q, v)

    assert g.delta == pytest.approx(central(lambda x: f(s=x), s, 1e-4 * s), rel=1e-6)
    h = 1e-4 * s
    gamma_fd = (f(s=s + h) - 2.0 * f() + f(s=s - h)) / h**2
    assert g.gamma == pytest.approx(gamma_fd, rel=1e-6)
    assert g.vega == pytest.approx(central(lambda x: f(v=x), v, 1e-5), rel=1e-6)
    assert g.rho == pytest.approx(central(lambda x: f(r=x), r, 1e-6), rel=1e-6)
    assert g.dividend_rho == pytest.approx(central(lambda x: f(q=x), q, 1e-6), rel=1e-6)
    # Theta is dV/dt = -dV/dT at fixed zero rates.
    assert g.theta == pytest.approx(-central(lambda x: f(t=x), t, 1e-6), rel=1e-6)


def test_theta_per_day() -> None:
    assert Greeks(0.5, 0.01, 40.0, -7.3, 50.0, -55.0).theta_per_day == pytest.approx(-0.02)


# --------------------------------------------------------------------------- engine on a snapshot

VALUATION = date(2025, 11, 12)
EXPIRY = date(2027, 3, 19)
CURVE = bootstrap_par_yield_curve(
    VALUATION,
    [
        ParYieldQuote(Tenor.parse(t), r)
        for t, r in {"3M": 0.043, "1Y": 0.0385, "2Y": 0.036, "5Y": 0.0365}.items()
    ],
)
MARKET = MarketSnapshot(
    timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
    valuation_date=VALUATION,
    curves={"USD-TSY": CURVE, "SPX-DIV": FlatForwardCurve(VALUATION, 0.013)},
    spots={"SPX": 5000.0},
    volatilities={"SPX": FlatVolatility(0.18)},
)
MODEL = BlackScholesModel("USD-TSY", "SPX-DIV")
ENGINE: PricingEngine[EuropeanOption, BlackScholesValuation] = AnalyticEuropeanEngine(MODEL)


@pytest.mark.parametrize("option_type", [CALL, PUT])
def test_engine_prices_with_model_inputs(option_type: OptionType) -> None:
    option = EuropeanOption("SPX", 5100.0, EXPIRY, option_type)
    inputs = MODEL.inputs("SPX", EXPIRY, 5100.0, MARKET)
    assert ENGINE.price(option, MARKET) == black_scholes(option_type, 5100.0, inputs)


@pytest.mark.parametrize("option_type", [CALL, PUT])
def test_greeks_match_snapshot_bumps(option_type: OptionType) -> None:
    # The analytic Greeks are the sensitivities to the market objects the risk service will
    # bump: the spot, the volatility surface, and a parallel zero-rate shift of each curve
    # (both curves are on ACT/365F, the model time axis).
    option = EuropeanOption("SPX", 5100.0, EXPIRY, option_type)
    g = ENGINE.price(option, MARKET).greeks

    def npv(market: MarketSnapshot) -> float:
        return ENGINE.price(option, market).npv

    h = 1e-4
    delta = (npv(MARKET.with_spot("SPX", 5000.5)) - npv(MARKET.with_spot("SPX", 4999.5))) / 1.0
    vega = (
        npv(MARKET.with_volatility("SPX", FlatVolatility(0.18 + h)))
        - npv(MARKET.with_volatility("SPX", FlatVolatility(0.18 - h)))
    ) / (2.0 * h)

    def curve_bump(name: str) -> float:
        base = MARKET.curve(name)
        up = npv(MARKET.with_curve(name, ZeroSpreadedCurve(base, h)))
        down = npv(MARKET.with_curve(name, ZeroSpreadedCurve(base, -h)))
        return (up - down) / (2.0 * h)

    assert g.delta == pytest.approx(delta, rel=1e-7)
    assert g.vega == pytest.approx(vega, rel=1e-7)
    assert g.rho == pytest.approx(curve_bump("USD-TSY"), rel=1e-7)
    assert g.dividend_rho == pytest.approx(curve_bump("SPX-DIV"), rel=1e-7)


def test_engine_rejects_expired_option() -> None:
    option = EuropeanOption("SPX", 5000.0, date(2025, 11, 11), CALL)
    with pytest.raises(PricerError, match="before the valuation date"):
        ENGINE.price(option, MARKET)
