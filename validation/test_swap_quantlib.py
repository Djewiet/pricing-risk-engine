"""Benchmark of the vanilla swap engine against QuantLib's ``OvernightIndexedSwap``.

Both libraries price on the same bootstrapped Treasury curve (handed to QuantLib as a
log-linear ``DiscountCurve``), optionally with a forecast curve shifted by a constant
continuously-compounded spread (``ZeroSpreadedTermStructure``) to exercise the
two-curve path. QuantLib's overnight index uses ``NullCalendar`` so that every day is a
fixing day and value dates equal accrual dates; QuantLib compounds the daily forwards one
by one, which independently checks our telescoped formula ``F(s) / F(e) - 1``.
"""

from datetime import date
from typing import Any

import pytest

from pricer.dates import THIRTY_360, ActualActualICMA, DayCount, Tenor
from pricer.engines import discount_swap
from pricer.instruments import InterestRateSwap, SwapDirection
from pricer.market import ParYieldQuote, ZeroSpreadedCurve, bootstrap_par_yield_curve

ql = pytest.importorskip("QuantLib")

VALUATION = date(2025, 8, 29)
RATES = {
    "1M": 0.0440, "3M": 0.0430, "6M": 0.0405, "1Y": 0.0385, "2Y": 0.0360, "3Y": 0.0355,
    "5Y": 0.0365, "7Y": 0.0385, "10Y": 0.0420, "20Y": 0.0480, "30Y": 0.0490,
}  # fmt: skip

N = 10_000_000.0
NPV_TOL = 1e-8 * N  # 1e-8 of notional: well below a cent per million
RATE_TOL = 1e-12

SWAPS = {
    "spot-5y": InterestRateSwap(VALUATION, date(2030, 8, 29), 0.037, N),
    "spot-30y-receiver": InterestRateSwap(
        VALUATION, date(2055, 8, 29), 0.045, N, SwapDirection.RECEIVER
    ),
    "forward-2y5y": InterestRateSwap(date(2027, 8, 31), date(2032, 8, 31), 0.04, N),
    "stub-eom": InterestRateSwap(date(2025, 9, 30), date(2033, 2, 28), 0.038, N),
    "semi-30-360-vs-quarterly": InterestRateSwap(
        VALUATION,
        date(2035, 8, 29),
        0.041,
        N,
        fixed_tenor=Tenor.parse("6M"),
        fixed_day_count=THIRTY_360,
        floating_tenor=Tenor.parse("3M"),
    ),
    "with-spread": InterestRateSwap(VALUATION, date(2040, 8, 29), 0.042, N, floating_spread=0.0015),
}


def to_ql(d: date) -> Any:
    return ql.Date(d.day, d.month, d.year)


def ql_day_count(day_count: DayCount) -> Any:
    assert not isinstance(day_count, ActualActualICMA)
    return {"ACT/360": ql.Actual360(), "30/360": ql.Thirty360(ql.Thirty360.BondBasis)}[
        day_count.name
    ]


def ql_schedule(swap: InterestRateSwap, tenor: Tenor) -> Any:
    return ql.Schedule(
        to_ql(swap.effective_date),
        to_ql(swap.maturity),
        ql.Period(str(tenor)),
        ql.NullCalendar(),
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Backward,
        False,
    )


@pytest.mark.parametrize("forecast_spread", [0.0, 0.0025], ids=["single-curve", "two-curve"])
@pytest.mark.parametrize("name", SWAPS)
def test_swap_matches_quantlib(name: str, forecast_spread: float) -> None:
    swap = SWAPS[name]
    discount = bootstrap_par_yield_curve(
        VALUATION, [ParYieldQuote(Tenor.parse(t), r) for t, r in RATES.items()]
    )
    forecast = ZeroSpreadedCurve(discount, forecast_spread) if forecast_spread else discount
    ours = discount_swap(swap, discount, forecast)

    ql.Settings.instance().evaluationDate = to_ql(VALUATION)
    discount_ql = ql.DiscountCurve(
        [to_ql(d) for d in (VALUATION, *discount.pillar_dates)],
        [1.0, *discount.pillar_discounts],
        ql.Actual365Fixed(),
    )
    discount_ql.enableExtrapolation()
    discount_handle = ql.YieldTermStructureHandle(discount_ql)
    forecast_handle = ql.YieldTermStructureHandle(
        ql.ZeroSpreadedTermStructure(
            discount_handle,
            ql.QuoteHandle(ql.SimpleQuote(forecast_spread)),
            ql.Continuous,
            ql.NoFrequency,
            ql.Actual365Fixed(),
        )
    )
    index = ql.OvernightIndex(
        "ON-NULL", 0, ql.USDCurrency(), ql.NullCalendar(), ql.Actual360(), forecast_handle
    )
    side = ql.Swap.Payer if swap.direction is SwapDirection.PAYER else ql.Swap.Receiver
    fixed_count = len(swap.fixed_leg)
    float_count = len(swap.floating_leg)
    theirs = ql.OvernightIndexedSwap(
        side,
        [N] * fixed_count,
        ql_schedule(swap, swap.fixed_tenor),
        swap.fixed_rate,
        ql_day_count(swap.fixed_day_count),
        [N] * float_count,
        ql_schedule(swap, swap.floating_tenor),
        index,
        swap.floating_spread,
        0,
        ql.Unadjusted,
        ql.NullCalendar(),
    )
    theirs.setPricingEngine(ql.DiscountingSwapEngine(discount_handle))

    assert ours.npv == pytest.approx(theirs.NPV(), abs=NPV_TOL)
    assert ours.fixed_leg_pv == pytest.approx(abs(theirs.fixedLegNPV()), abs=NPV_TOL)
    assert ours.floating_leg_pv == pytest.approx(abs(theirs.overnightLegNPV()), abs=NPV_TOL)
    assert ours.par_rate == pytest.approx(theirs.fairRate(), abs=RATE_TOL)
