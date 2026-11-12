import math
from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from pricer.dates import Tenor
from pricer.engines import DiscountingSwapEngine, PricingEngine, SwapValuation, discount_swap
from pricer.errors import MissingMarketDataError, PricerError
from pricer.instruments import InterestRateSwap, SwapDirection
from pricer.market import (
    FlatForwardCurve,
    MarketSnapshot,
    ParYieldQuote,
    ZeroSpreadedCurve,
    bootstrap_par_yield_curve,
)
from pricer.risk import ONE_BP, parallel_dv01

REF = date(2025, 8, 29)
CURVE = bootstrap_par_yield_curve(
    REF,
    [
        ParYieldQuote(Tenor.parse(t), r)
        for t, r in {"6M": 0.0405, "1Y": 0.0385, "2Y": 0.036, "5Y": 0.0365, "10Y": 0.042}.items()
    ],
)
N = 10_000_000.0
SWAP = InterestRateSwap(REF, date(2032, 8, 29), 0.037, notional=N)


def test_single_curve_floating_leg_telescopes() -> None:
    # Closed form: sum of N * (D(s)/D(e) - 1) * D(e) = N * (D(t0) - D(T)).
    value = discount_swap(SWAP, CURVE, CURVE)
    expected = N * (CURVE.discount(REF) - CURVE.discount(SWAP.maturity))
    assert value.floating_leg_pv == pytest.approx(expected, rel=1e-13)


def test_single_curve_par_rate_closed_form() -> None:
    value = discount_swap(SWAP, CURVE, CURVE)
    annuity = sum(c.accrual * CURVE.discount(c.payment_date) for c in SWAP.fixed_leg)
    expected = (1.0 - CURVE.discount(SWAP.maturity)) / annuity
    assert value.par_rate == pytest.approx(expected, rel=1e-13)
    assert value.annuity == pytest.approx(N * annuity, rel=1e-13)


def test_swap_at_par_rate_is_worth_zero() -> None:
    par = discount_swap(SWAP, CURVE, CURVE).par_rate
    at_par = replace(SWAP, fixed_rate=par)
    assert discount_swap(at_par, CURVE, CURVE).npv == pytest.approx(0.0, abs=1e-6)


def test_payer_and_receiver_are_opposite() -> None:
    payer = discount_swap(SWAP, CURVE, CURVE)
    receiver = discount_swap(replace(SWAP, direction=SwapDirection.RECEIVER), CURVE, CURVE)
    assert payer.npv == pytest.approx(payer.floating_leg_pv - payer.fixed_leg_pv)
    assert receiver.npv == pytest.approx(-payer.npv)
    assert payer.fixed_leg_pv == pytest.approx(SWAP.fixed_rate * payer.annuity)


def test_flat_curve_forward_rate() -> None:
    # Continuous rate r on ACT/365F, accrual on ACT/360: R = (exp(r d/365) - 1) * 360 / d.
    r = 0.03
    curve = FlatForwardCurve(REF, r)
    swap = InterestRateSwap(REF, date(2026, 8, 29), 0.0, notional=1.0)
    days = 365
    expected_rate = (math.exp(r * days / 365) - 1) * 360 / days
    value = discount_swap(swap, curve, curve)
    assert value.par_rate == pytest.approx(expected_rate, rel=1e-13)


def test_spread_shifts_par_rate_one_for_one_when_legs_match() -> None:
    base = discount_swap(SWAP, CURVE, CURVE).par_rate
    spreaded = discount_swap(replace(SWAP, floating_spread=0.0025), CURVE, CURVE).par_rate
    assert spreaded - base == pytest.approx(0.0025, abs=1e-14)


def test_forecast_and_discount_curves_play_different_roles() -> None:
    higher_forecast = ZeroSpreadedCurve(CURVE, 0.002)
    single = discount_swap(SWAP, CURVE, CURVE)
    dual = discount_swap(SWAP, CURVE, higher_forecast)
    assert dual.annuity == single.annuity  # discounting unchanged
    assert dual.par_rate > single.par_rate  # higher projected fixings
    assert dual.par_rate - single.par_rate == pytest.approx(0.002, rel=0.05)


def test_forward_starting_swap() -> None:
    swap = InterestRateSwap(date(2026, 8, 29), date(2031, 8, 29), 0.04, notional=N)
    value = discount_swap(swap, CURVE, CURVE)
    expected = N * (CURVE.discount(date(2026, 8, 29)) - CURVE.discount(date(2031, 8, 29)))
    assert value.floating_leg_pv == pytest.approx(expected, rel=1e-13)


def test_valuation_on_a_payment_date_excludes_that_payment() -> None:
    curve = FlatForwardCurve(date(2026, 8, 29), 0.03)
    value = discount_swap(SWAP, curve, curve)
    remaining = [c for c in SWAP.fixed_leg if c.payment_date > date(2026, 8, 29)]
    assert value.annuity == pytest.approx(
        N * sum(c.accrual * curve.discount(c.payment_date) for c in remaining)
    )


def test_errors() -> None:
    with pytest.raises(PricerError, match="share a reference date"):
        discount_swap(SWAP, CURVE, FlatForwardCurve(date(2025, 8, 28), 0.03))
    after = FlatForwardCurve(date(2033, 1, 1), 0.03)
    with pytest.raises(PricerError, match="no cash flow"):
        discount_swap(SWAP, after, after)
    mid = FlatForwardCurve(date(2026, 1, 1), 0.03)
    with pytest.raises(PricerError, match="fixings"):
        discount_swap(SWAP, mid, mid)


def test_engine_and_dv01_through_snapshot() -> None:
    market = MarketSnapshot(datetime(2025, 8, 29, 21, tzinfo=UTC), REF, curves={"UST": CURVE})
    engine: PricingEngine[InterestRateSwap, SwapValuation] = DiscountingSwapEngine("UST", "UST")
    value = engine.price(SWAP, market)
    assert value == discount_swap(SWAP, CURVE, CURVE)

    dv01 = parallel_dv01(lambda m: engine.price(SWAP, m).npv, market, "UST")
    # A payer swap loses when rates fall; its DV01 is about the annuity times 1bp.
    assert dv01 < 0.0
    assert -dv01 == pytest.approx(value.annuity * ONE_BP, rel=0.1)

    with pytest.raises(MissingMarketDataError):
        DiscountingSwapEngine("UST", "SOFR").price(SWAP, market)
