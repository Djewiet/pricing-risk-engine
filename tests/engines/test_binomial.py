import math
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pricer.engines import (
    AnalyticEuropeanEngine,
    BinomialTreeEngine,
    PricingEngine,
    TreeValuation,
    binomial_tree,
    black_scholes,
)
from pricer.errors import PricerError
from pricer.greeks import bump_greeks
from pricer.instruments import AmericanOption, EuropeanOption, OptionType, VanillaOption
from pricer.market import FlatForwardCurve, FlatVolatility, MarketSnapshot
from pricer.models import BlackScholesInputs, BlackScholesModel

CALL, PUT = OptionType.CALL, OptionType.PUT
EXPIRY = date(2026, 11, 12)  # the date is irrelevant to binomial_tree, T comes from inputs


def make_inputs(s: float, t: float, r: float, q: float, sigma: float) -> BlackScholesInputs:
    return BlackScholesInputs(s, t, math.exp(-r * t), math.exp(-q * t), sigma)


def tree(
    option_type: OptionType, k: float, inputs: BlackScholesInputs, steps: int, *, american: bool
) -> TreeValuation:
    cls = AmericanOption if american else EuropeanOption
    return binomial_tree(cls("X", k, EXPIRY, option_type), inputs, steps)


def assert_same_tree(a: TreeValuation, b: TreeValuation) -> None:
    for name in ("npv", "delta", "gamma", "theta"):
        assert getattr(a, name) == pytest.approx(getattr(b, name), rel=1e-12, abs=1e-12), name


BASE = make_inputs(100.0, 1.0, 0.05, 0.02, 0.25)

# --------------------------------------------------------------------------- European: convergence


@pytest.mark.parametrize("option_type", [CALL, PUT])
@pytest.mark.parametrize("strike", [80.0, 100.0, 125.0])
def test_european_tree_converges_to_black_scholes(option_type: OptionType, strike: float) -> None:
    # CRR converges in O(1/N): the error at 2000 steps is a few 1e-3 at most for S = 100,
    # and quadrupling N divides it by about 4 (the oscillation with N is handled by using
    # steps of the same parity).
    exact = black_scholes(option_type, strike, BASE).npv
    coarse = abs(tree(option_type, strike, BASE, 500, american=False).npv - exact)
    fine = abs(tree(option_type, strike, BASE, 2000, american=False).npv - exact)
    assert fine < 5e-3
    assert fine < coarse / 2.0


def test_european_tree_greeks_converge_to_analytic() -> None:
    exact = black_scholes(PUT, 100.0, BASE).greeks
    value = tree(PUT, 100.0, BASE, 2000, american=False)
    assert value.delta == pytest.approx(exact.delta, abs=1e-3)
    assert value.gamma == pytest.approx(exact.gamma, rel=1e-2)
    assert value.theta == pytest.approx(exact.theta, rel=1e-2)
    assert value.steps == 2000


spots = st.floats(50.0, 200.0)
times = st.floats(0.05, 5.0)
rates = st.floats(-0.02, 0.10)
yields = st.floats(0.0, 0.06)
vols = st.floats(0.1, 0.8)


@settings(max_examples=50)
@given(s=spots, t=times, r=rates, q=yields, v=vols)
def test_european_tree_satisfies_put_call_parity_exactly(
    s: float, t: float, r: float, q: float, v: float
) -> None:
    # p makes the discounted spot a martingale on each step, so the tree prices the forward
    # S Dq - K Dr exactly, whatever N: parity holds to rounding, not only in the limit.
    inputs = make_inputs(s, t, r, q, v)
    call = tree(CALL, 100.0, inputs, 200, american=False).npv
    put = tree(PUT, 100.0, inputs, 200, american=False).npv
    forward_value = s * inputs.dividend_discount_factor - 100.0 * inputs.discount_factor
    assert call - put == pytest.approx(forward_value, abs=1e-11 * s)


# --------------------------------------------------------------------------- early exercise


@settings(max_examples=50)
@given(s=spots, t=times, r=rates, q=yields, v=vols, option_type=st.sampled_from([CALL, PUT]))
def test_american_bounds(
    s: float, t: float, r: float, q: float, v: float, option_type: OptionType
) -> None:
    # The right to exercise early is worth something non-negative, and exercising now is
    # always possible: American >= max(European, payoff).
    inputs = make_inputs(s, t, r, q, v)
    american = tree(option_type, 100.0, inputs, 200, american=True).npv
    european = tree(option_type, 100.0, inputs, 200, american=False).npv
    payoff = max(option_type.sign * (s - 100.0), 0.0)
    assert american >= european - 1e-12 * s
    assert american >= payoff - 1e-12 * s


@pytest.mark.parametrize("r", [0.0, 0.05])
def test_american_call_without_dividends_is_european(r: float) -> None:
    # Merton: with q = 0 and r >= 0, the call is worth more alive than exercised
    # (C >= S - K Dr >= S - K), so it is never exercised early. The trees are identical.
    inputs = make_inputs(100.0, 2.0, r, 0.0, 0.3)
    for strike in (70.0, 100.0, 130.0):
        american = tree(CALL, strike, inputs, 400, american=True)
        european = tree(CALL, strike, inputs, 400, american=False)
        # At r = 0 deep in the money, continuation equals the payoff: rounding decides.
        assert_same_tree(american, european)


def test_american_put_with_negative_rates_is_european() -> None:
    # Symmetric argument: with r <= 0 (and q >= 0), P >= K Dr - S Dq >= K - S.
    inputs = make_inputs(100.0, 2.0, -0.01, 0.0, 0.3)
    for strike in (70.0, 100.0, 130.0):
        assert_same_tree(
            tree(PUT, strike, inputs, 400, american=True),
            tree(PUT, strike, inputs, 400, american=False),
        )


def test_early_exercise_premium() -> None:
    # Positive rates make an American put worth more than its European twin: the holder
    # can receive the strike now and earn interest on it.
    american = tree(PUT, 100.0, BASE, 1000, american=True).npv
    european = tree(PUT, 100.0, BASE, 1000, american=False).npv
    assert american - european > 0.1
    # Dividends make an American call worth more: exercising captures them.
    dividends = make_inputs(100.0, 1.0, 0.01, 0.08, 0.25)
    assert (
        tree(CALL, 80.0, dividends, 1000, american=True).npv
        > tree(CALL, 80.0, dividends, 1000, american=False).npv + 0.1
    )


def test_deep_in_the_money_american_put_is_exercised_now() -> None:
    inputs = make_inputs(40.0, 1.0, 0.10, 0.0, 0.2)
    value = tree(PUT, 100.0, inputs, 500, american=True)
    assert value.npv == pytest.approx(60.0, abs=1e-12)
    assert value.delta == pytest.approx(-1.0, abs=1e-12)
    assert value.gamma == pytest.approx(0.0, abs=1e-12)


@settings(max_examples=30)
@given(s=spots, r=rates, q=yields, v=vols)
def test_american_value_increases_with_maturity(s: float, r: float, q: float, v: float) -> None:
    # A longer American option includes every exercise strategy of the shorter one. (Not
    # true of a European option: a deep in-the-money European put can lose value with time.)
    short = tree(PUT, 100.0, make_inputs(s, 0.5, r, q, v), 300, american=True).npv
    long = tree(PUT, 100.0, make_inputs(s, 1.0, r, q, v), 600, american=True).npv
    assert long >= short - 1e-3


# --------------------------------------------------------------------------- edge cases


@pytest.mark.parametrize(("spot", "expected"), [(110.0, 10.0), (90.0, 0.0)])
def test_expiring_today_is_worth_the_payoff(spot: float, expected: float) -> None:
    value = tree(CALL, 100.0, BlackScholesInputs(spot, 0.0, 1.0, 1.0, 0.2), 100, american=True)
    assert value.npv == expected
    assert value.delta == (1.0 if expected else 0.0)
    assert value.steps == 0


def test_invalid_trees_are_rejected() -> None:
    with pytest.raises(ValueError, match="at least 2 steps"):
        tree(CALL, 100.0, BASE, 1, american=False)
    with pytest.raises(PricerError, match="positive volatility"):
        tree(CALL, 100.0, replace(BASE, volatility=0.0), 100, american=False)
    # 1% vol, 50% rates, 2 steps: the forward grows faster than the up move, p > 1.
    with pytest.raises(PricerError, match="outside"):
        tree(CALL, 100.0, make_inputs(100.0, 1.0, 0.5, 0.0, 0.01), 2, american=False)


# --------------------------------------------------------------------------- engine on a snapshot

VALUATION = date(2025, 11, 12)
MARKET = MarketSnapshot(
    timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
    valuation_date=VALUATION,
    curves={"R": FlatForwardCurve(VALUATION, 0.04), "Q": FlatForwardCurve(VALUATION, 0.01)},
    spots={"SPX": 5000.0},
    volatilities={"SPX": FlatVolatility(0.2)},
)
MODEL = BlackScholesModel("R", "Q")
ENGINE: PricingEngine[VanillaOption, TreeValuation] = BinomialTreeEngine(MODEL, steps=800)


def test_engine_prices_with_model_inputs() -> None:
    option = AmericanOption("SPX", 5200.0, date(2026, 12, 18), PUT)
    inputs = MODEL.inputs("SPX", option.expiry, option.strike, MARKET)
    assert ENGINE.price(option, MARKET) == binomial_tree(option, inputs, 800)


def test_same_model_as_the_analytic_engine() -> None:
    option = EuropeanOption("SPX", 5200.0, date(2026, 12, 18), CALL)
    analytic = AnalyticEuropeanEngine(MODEL).price(option, MARKET).npv
    assert ENGINE.price(option, MARKET).npv == pytest.approx(analytic, rel=1e-3)


def test_bump_greeks_give_the_tree_its_vega_and_rho() -> None:
    # The tree has no vega or rho of its own; bump_greeks provides them unchanged. A tree's
    # value is not smooth in its inputs (nodes move), so compare loosely with the closed
    # form on a European option.
    option = EuropeanOption("SPX", 5200.0, date(2026, 12, 18), CALL)
    bumped = bump_greeks(
        lambda m: ENGINE.price(option, m).npv, MARKET, "SPX", "R", dividend_curve="Q"
    )
    exact = AnalyticEuropeanEngine(MODEL).price(option, MARKET).greeks
    assert bumped.vega == pytest.approx(exact.vega, rel=1e-2)
    assert bumped.rho == pytest.approx(exact.rho, rel=1e-2)
