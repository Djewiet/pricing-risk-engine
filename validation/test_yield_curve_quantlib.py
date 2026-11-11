"""Benchmark of the par-yield bootstrap against QuantLib.

QuantLib setup reproducing our conventions exactly:
``FixedRateBondHelper`` quoted at a clean price of 100 with the par yield as coupon,
zero settlement days, ``NullCalendar`` and ``Unadjusted`` dates, backward schedule without
end-of-month rule, ACT/ACT ISMA coupons, and a ``PiecewiseLogLinearDiscount`` curve on
ACT/365F. Any remaining difference is therefore an implementation error, not a modelling
choice, and the tolerance is set at the accuracy of the QuantLib solver.
"""

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest

from pricer.dates import Tenor
from pricer.market import ParYieldQuote, bootstrap_par_yield_curve

ql = pytest.importorskip("QuantLib")

TENORS = ("1M", "6W", "2M", "3M", "4M", "6M", "1Y", "2Y", "3Y", "5Y", "7Y", "10Y", "20Y", "30Y")

SHAPES: dict[str, tuple[float, ...]] = {
    "normal": (4.30, 4.31, 4.32, 4.33, 4.35, 4.40, 4.45, 4.55, 4.62, 4.75, 4.85, 4.95, 5.10, 5.05),
    "inverted": (5.50, 5.49, 5.48, 5.45, 5.40, 5.30, 5.05, 4.70, 4.45, 4.25, 4.20, 4.15, 4.30,
                 4.20),
    "humped": (4.40, 4.39, 4.35, 4.30, 4.20, 4.05, 3.85, 3.60, 3.55, 3.65, 3.85, 4.20, 4.80, 4.90),
    "negative": (-0.60, -0.60, -0.59, -0.58, -0.57, -0.55, -0.50, -0.40, -0.30, -0.10, 0.05, 0.20,
                 0.40, 0.45),
    "flat": (3.0,) * 14,
}  # fmt: skip

# Reference dates chosen to stress date generation: month end, leap day, 31st, mid-month.
REFERENCE_DATES = (
    date(2025, 8, 29),
    date(2025, 8, 31),
    date(2024, 2, 29),
    date(2025, 1, 31),
    date(2025, 3, 15),
    date(2023, 12, 29),
)

# QuantLib solves each pillar to an accuracy of 1e-12 on the discount factor by default,
# so agreement is expected to ~1e-12, not to machine precision.
TOLERANCE = 1e-11


def to_ql(d: date) -> Any:
    return ql.Date(d.day, d.month, d.year)


def quantlib_curve(reference: date, rates: dict[str, float]) -> Any:
    ref = to_ql(reference)
    ql.Settings.instance().evaluationDate = ref
    helpers = []
    for tenor, rate in rates.items():
        schedule = ql.Schedule(
            ref,
            ref + ql.Period(tenor),
            ql.Period(6, ql.Months),
            ql.NullCalendar(),
            ql.Unadjusted,
            ql.Unadjusted,
            ql.DateGeneration.Backward,
            False,
        )
        helpers.append(
            ql.FixedRateBondHelper(
                ql.QuoteHandle(ql.SimpleQuote(100.0)),
                0,
                100.0,
                schedule,
                [rate],
                ql.ActualActual(ql.ActualActual.ISMA),
                ql.Unadjusted,
            )
        )
    curve = ql.PiecewiseLogLinearDiscount(ref, helpers, ql.Actual365Fixed())
    curve.enableExtrapolation()
    return curve


def check_dates(reference: date) -> Iterator[date]:
    """Every 17 days over 35 years: hits pillars' neighbourhoods and the extrapolated tail."""
    d = reference
    while d < reference + timedelta(days=365 * 35):
        d += timedelta(days=17)
        yield d


@pytest.mark.parametrize("reference", REFERENCE_DATES, ids=str)
@pytest.mark.parametrize("shape", SHAPES)
def test_discount_factors_match_quantlib(reference: date, shape: str) -> None:
    rates = {t: r / 100.0 for t, r in zip(TENORS, SHAPES[shape], strict=True)}
    ours = bootstrap_par_yield_curve(
        reference, [ParYieldQuote(Tenor.parse(t), r) for t, r in rates.items()]
    )
    theirs = quantlib_curve(reference, rates)

    for pillar, discount in zip(ours.pillar_dates, ours.pillar_discounts, strict=True):
        assert discount == pytest.approx(theirs.discount(to_ql(pillar)), abs=TOLERANCE)
    worst = max(abs(ours.discount(d) - theirs.discount(to_ql(d))) for d in check_dates(reference))
    assert worst < TOLERANCE
