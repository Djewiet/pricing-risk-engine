import math
from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pytest

from pricer.engines import (
    AnalyticEuropeanEngine,
    MonteCarloEuropeanEngine,
    MonteCarloValuation,
    PricingEngine,
    black_scholes,
    monte_carlo_european,
)
from pricer.errors import PricerError
from pricer.greeks import BumpSizes, bump_greeks
from pricer.instruments import EuropeanOption, OptionType
from pricer.market import FlatForwardCurve, FlatVolatility, MarketSnapshot
from pricer.models import BlackScholesInputs, BlackScholesModel

CALL, PUT = OptionType.CALL, OptionType.PUT
EXPIRY = date(2026, 11, 13)  # irrelevant to monte_carlo_european, T comes from the inputs
INPUTS = BlackScholesInputs(100.0, 1.0, math.exp(-0.05), math.exp(-0.02), 0.25)


def option(option_type: OptionType, strike: float) -> EuropeanOption:
    return EuropeanOption("X", strike, EXPIRY, option_type)


def run(
    option_type: OptionType,
    strike: float,
    paths: int = 200_000,
    seed: int = 7,
    *,
    antithetic: bool = True,
    control_variate: bool = True,
    inputs: BlackScholesInputs = INPUTS,
) -> MonteCarloValuation:
    return monte_carlo_european(
        option(option_type, strike),
        inputs,
        paths,
        np.random.default_rng(seed),
        antithetic=antithetic,
        control_variate=control_variate,
    )


VARIANTS = [(False, False), (True, False), (False, True), (True, True)]


@pytest.mark.parametrize(("antithetic", "control_variate"), VARIANTS)
@pytest.mark.parametrize("option_type", [CALL, PUT])
@pytest.mark.parametrize("strike", [80.0, 100.0, 130.0])
def test_estimate_is_within_four_standard_errors_of_black_scholes(
    antithetic: bool, control_variate: bool, option_type: OptionType, strike: float
) -> None:
    # The estimator is unbiased (exact simulation of S_T), so the error is N(0, se^2) up to
    # the 1/n bias of the estimated beta. Four standard errors: a 6e-5 chance per case
    # of a false failure for a random seed; the seed is fixed, so the test is deterministic.
    exact = black_scholes(option_type, strike, INPUTS).npv
    value = run(option_type, strike, antithetic=antithetic, control_variate=control_variate)
    assert abs(value.npv - exact) < 4.0 * value.std_error
    low, high = value.confidence_interval(4.0)
    assert low < exact < high


def test_same_seed_same_result_different_seed_different_result() -> None:
    assert run(CALL, 100.0, seed=1) == run(CALL, 100.0, seed=1)
    assert run(CALL, 100.0, seed=1).npv != run(CALL, 100.0, seed=2).npv


def test_standard_error_decreases_as_one_over_square_root_of_paths() -> None:
    small = run(CALL, 100.0, paths=50_000, antithetic=False, control_variate=False)
    large = run(CALL, 100.0, paths=800_000, antithetic=False, control_variate=False)
    # 16 times the paths, a quarter of the error (the standard deviation estimate itself
    # has a relative error of ~1/sqrt(2n), well inside 5%).
    assert large.std_error == pytest.approx(small.std_error / 4.0, rel=0.05)


@pytest.mark.parametrize(("strike", "min_gain"), [(80.0, 100.0), (100.0, 20.0), (130.0, 15.0)])
def test_variance_reduction(strike: float, min_gain: float) -> None:
    # Variance ratio plain / reduced, for the same number of paths. Each technique helps,
    # the control variate most for in-the-money calls (payoff almost linear in S_T).
    plain = run(CALL, strike, antithetic=False, control_variate=False).std_error
    antithetic = run(CALL, strike, control_variate=False).std_error
    control = run(CALL, strike, antithetic=False).std_error
    both = run(CALL, strike).std_error
    assert antithetic < plain
    assert control < plain
    assert both < min(antithetic, control)
    assert (plain / both) ** 2 > min_gain


def test_put_call_parity_is_exact_with_the_control_variate() -> None:
    # Y_call - Y_put = X - K Dr is linear in the control X, so the two regressions differ by
    # exactly beta = 1 and the two residuals are identical: the Monte Carlo errors cancel
    # and C - P = S Dq - K Dr to rounding, with any number of paths.
    call, put = run(CALL, 105.0, paths=1_000), run(PUT, 105.0, paths=1_000)
    forward_value = 100.0 * INPUTS.dividend_discount_factor - 105.0 * INPUTS.discount_factor
    assert call.npv - put.npv == pytest.approx(forward_value, abs=1e-12)
    assert call.control_beta - put.control_beta == pytest.approx(1.0, abs=1e-12)
    assert call.std_error == pytest.approx(put.std_error, rel=1e-9)


def test_zero_volatility_is_deterministic() -> None:
    inputs = replace(INPUTS, volatility=0.0)
    value = run(CALL, 90.0, inputs=inputs)
    expected = black_scholes(CALL, 90.0, inputs).npv
    assert value.npv == pytest.approx(expected, rel=1e-14)
    assert value.std_error == 0.0
    assert value.control_beta == 0.0  # the control is constant: nothing to regress on


def test_invalid_path_counts() -> None:
    with pytest.raises(ValueError, match="at least 4 paths"):
        run(CALL, 100.0, paths=2)
    with pytest.raises(ValueError, match="even number"):
        run(CALL, 100.0, paths=1001)
    assert run(CALL, 100.0, paths=1001, antithetic=False).paths == 1001


# --------------------------------------------------------------------------- engine on a snapshot

VALUATION = date(2025, 11, 13)
MARKET = MarketSnapshot(
    timestamp=datetime(2025, 11, 13, 21, 0, tzinfo=UTC),
    valuation_date=VALUATION,
    curves={"R": FlatForwardCurve(VALUATION, 0.04), "Q": FlatForwardCurve(VALUATION, 0.01)},
    spots={"SPX": 5000.0},
    volatilities={"SPX": FlatVolatility(0.2)},
)
MODEL = BlackScholesModel("R", "Q")
ENGINE: PricingEngine[EuropeanOption, MonteCarloValuation] = MonteCarloEuropeanEngine(
    MODEL, paths=200_000, seed=11
)
SPX_CALL = EuropeanOption("SPX", 5200.0, date(2026, 12, 18), CALL)


def test_engine_is_a_pure_function_of_its_inputs() -> None:
    # The engine holds a seed, not a generator: pricing twice gives the same number.
    assert ENGINE.price(SPX_CALL, MARKET) == ENGINE.price(SPX_CALL, MARKET)
    inputs = MODEL.inputs("SPX", SPX_CALL.expiry, SPX_CALL.strike, MARKET)
    expected = monte_carlo_european(SPX_CALL, inputs, 200_000, np.random.default_rng(11))
    assert ENGINE.price(SPX_CALL, MARKET) == expected


def test_engine_agrees_with_the_closed_form() -> None:
    value = ENGINE.price(SPX_CALL, MARKET)
    exact = AnalyticEuropeanEngine(MODEL).price(SPX_CALL, MARKET).npv
    assert abs(value.npv - exact) < 4.0 * value.std_error


def test_expiring_today_is_worth_the_payoff() -> None:
    option = EuropeanOption("SPX", 4900.0, VALUATION, CALL)
    assert ENGINE.price(option, MARKET) == MonteCarloValuation(100.0, 0.0, 0, 0.0)
    with pytest.raises(PricerError, match="before the valuation date"):
        ENGINE.price(replace(option, expiry=date(2025, 11, 12)), MARKET)


def test_bump_greeks_with_common_random_numbers() -> None:
    # Every bumped valuation reuses the engine's seed, so the noise cancels in the
    # differences: delta, vega and rho by bump are close to the analytic values, although
    # each price is only known to about 1e-3 relative. With independent seeds the delta
    # would be noise of order std_error / bump ~ 0.3.
    bumped = bump_greeks(
        lambda m: ENGINE.price(SPX_CALL, m).npv,
        MARKET,
        "SPX",
        "R",
        dividend_curve="Q",
        bumps=BumpSizes(spot_relative=1e-2, volatility=1e-2),
    )
    exact = AnalyticEuropeanEngine(MODEL).price(SPX_CALL, MARKET).greeks
    assert bumped.delta == pytest.approx(exact.delta, rel=1e-2)
    assert bumped.vega == pytest.approx(exact.vega, rel=1e-2)
    assert bumped.rho == pytest.approx(exact.rho, rel=1e-2)
