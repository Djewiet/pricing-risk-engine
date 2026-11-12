"""Benchmark of fixed-rate bond pricing and yield analytics against QuantLib.

The discount curve is our bootstrapped curve, handed to QuantLib as a ``DiscountCurve``
(log-linear on discount factors, ACT/365F): both libraries discount on exactly the same
curve, so the comparison isolates cash-flow generation, accrual, discounting and the yield
analytics. Bonds use NullCalendar, unadjusted dates, backward schedules, ACT/ACT ISMA,
zero settlement days.
"""

from datetime import date
from typing import Any

import pytest

from pricer.analytics import yield_analytics, yield_to_maturity, z_spread
from pricer.dates import Tenor
from pricer.engines import discount_bond
from pricer.instruments import FixedRateBond
from pricer.market import DiscountCurve, ParYieldQuote, bootstrap_par_yield_curve

ql = pytest.importorskip("QuantLib")

VALUATION_DATES = (date(2025, 8, 29), date(2025, 11, 12), date(2024, 2, 29))
RATES = {
    "1M": 0.0440, "3M": 0.0430, "6M": 0.0405, "1Y": 0.0385, "2Y": 0.0360, "3Y": 0.0355,
    "5Y": 0.0365, "7Y": 0.0385, "10Y": 0.0420, "20Y": 0.0480, "30Y": 0.0490,
}  # fmt: skip

# (issue, maturity, coupon): seasoned, new, short-stub, end-of-month, zero-coupon, long bonds.
BONDS = (
    (date(2023, 8, 31), date(2033, 8, 31), 0.0425),
    (date(2020, 2, 29), date(2030, 2, 28), 0.0150),
    (date(2024, 1, 10), date(2031, 6, 15), 0.0700),
    (date(2021, 5, 15), date(2051, 5, 15), 0.0237),
    (date(2022, 11, 30), date(2027, 11, 30), 0.0),
    (date(2023, 12, 1), date(2026, 3, 1), 0.0525),
)

PRICE_TOL = 1e-10
YIELD_TOL = 1e-11
RISK_RTOL = 1e-9


def to_ql(d: date) -> Any:
    return ql.Date(d.day, d.month, d.year)


def ql_curve(curve: DiscountCurve) -> Any:
    dates = [curve.reference_date, *curve.pillar_dates]
    curve_ql = ql.DiscountCurve(
        [to_ql(d) for d in dates], [1.0, *curve.pillar_discounts], ql.Actual365Fixed()
    )
    curve_ql.enableExtrapolation()
    return curve_ql


def ql_bond(bond: FixedRateBond) -> Any:
    schedule = ql.Schedule(
        to_ql(bond.issue_date),
        to_ql(bond.maturity),
        ql.Period(6, ql.Months),
        ql.NullCalendar(),
        ql.Unadjusted,
        ql.Unadjusted,
        ql.DateGeneration.Backward,
        False,
    )
    return ql.FixedRateBond(
        0,
        100.0,
        schedule,
        [bond.coupon_rate],
        ql.ActualActual(ql.ActualActual.ISMA),
        ql.Unadjusted,
        100.0,
        to_ql(bond.issue_date),
    )


@pytest.mark.parametrize("valuation", VALUATION_DATES, ids=str)
@pytest.mark.parametrize(("issue", "maturity", "coupon"), BONDS, ids=str)
def test_bond_matches_quantlib(valuation: date, issue: date, maturity: date, coupon: float) -> None:
    assert issue <= valuation < maturity, "every bond must be alive at every valuation date"
    curve = bootstrap_par_yield_curve(
        valuation, [ParYieldQuote(Tenor.parse(t), r) for t, r in RATES.items()]
    )
    bond = FixedRateBond(issue, maturity, coupon)
    ours = discount_bond(bond, curve)

    ql.Settings.instance().evaluationDate = to_ql(valuation)
    curve_ql = ql_curve(curve)
    theirs = ql_bond(bond)
    theirs.setPricingEngine(ql.DiscountingBondEngine(ql.YieldTermStructureHandle(curve_ql)))

    assert ours.clean_price == pytest.approx(theirs.cleanPrice(), abs=PRICE_TOL)
    assert ours.dirty_price == pytest.approx(theirs.dirtyPrice(), abs=PRICE_TOL)
    assert ours.accrued_interest == pytest.approx(theirs.accruedAmount(), abs=PRICE_TOL)

    day_count = ql.ActualActual(ql.ActualActual.ISMA)
    clean = ql.BondPrice(ours.clean_price, ql.BondPrice.Clean)
    y_ql = theirs.bondYield(
        clean, day_count, ql.Compounded, ql.Semiannual, to_ql(valuation), 1e-14, 1000
    )
    y = yield_to_maturity(bond, ours.clean_price, valuation)
    assert y == pytest.approx(y_ql, abs=YIELD_TOL)

    rate = ql.InterestRate(y, day_count, ql.Compounded, ql.Semiannual)
    risk = yield_analytics(bond, y, valuation)
    bf = ql.BondFunctions
    assert risk.modified_duration == pytest.approx(
        bf.duration(theirs, rate, ql.Duration.Modified), rel=RISK_RTOL
    )
    assert risk.macaulay_duration == pytest.approx(
        bf.duration(theirs, rate, ql.Duration.Macaulay), rel=RISK_RTOL
    )
    assert risk.convexity == pytest.approx(bf.convexity(theirs, rate), rel=RISK_RTOL)

    cheap = ql.BondPrice(ours.clean_price - 2.0, ql.BondPrice.Clean)
    z_ql = bf.zSpread(theirs, cheap, curve_ql, ql.Actual365Fixed(), ql.Continuous, ql.NoFrequency)
    assert z_spread(bond, ours.clean_price - 2.0, curve) == pytest.approx(z_ql, abs=1e-9)
