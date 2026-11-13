"""QuantLib objects reproducing the library's option conventions, shared by the option
benchmarks and the validation report.

Conventions: ``NullCalendar``, ACT/365F on every time axis (curves, volatility), zero
settlement days, a ``BlackScholesMertonProcess`` with a flat ``BlackConstantVol``. With these
settings ``T``, the zero rates and the variance are the same numbers on both sides, so any
remaining difference is an implementation difference.
"""

from datetime import date
from typing import Any

import QuantLib as ql  # noqa: N813 - the conventional alias in QuantLib-Python code

from pricer.instruments import OptionType, VanillaOption
from pricer.market import DiscountCurve, FlatForwardCurve, YieldCurve

#: Valuation date of the option benchmarks and of the report.
VALUATION = date(2025, 11, 12)


def to_ql(d: date) -> Any:
    """QuantLib date of ``d``."""
    return ql.Date(d.day, d.month, d.year)


def ql_curve(curve: YieldCurve) -> Any:
    """QuantLib term structure identical to ``curve`` (flat-forward or discount curve)."""
    if isinstance(curve, FlatForwardCurve):
        return ql.FlatForward(to_ql(curve.reference_date), curve.rate, ql.Actual365Fixed())
    if not isinstance(curve, DiscountCurve):
        msg = f"No QuantLib equivalent for {type(curve).__name__}"
        raise TypeError(msg)
    dates = [curve.reference_date, *curve.pillar_dates]
    curve_ql = ql.DiscountCurve(
        [to_ql(d) for d in dates], [1.0, *curve.pillar_discounts], ql.Actual365Fixed()
    )
    curve_ql.enableExtrapolation()
    return curve_ql


def bsm_process(spot: float, rates: YieldCurve, dividends: YieldCurve, vol: float) -> Any:
    """Black-Scholes-Merton process, with the evaluation date set to :data:`VALUATION`."""
    ql.Settings.instance().evaluationDate = to_ql(VALUATION)
    return ql.BlackScholesMertonProcess(
        ql.QuoteHandle(ql.SimpleQuote(spot)),
        ql.YieldTermStructureHandle(ql_curve(dividends)),
        ql.YieldTermStructureHandle(ql_curve(rates)),
        ql.BlackVolTermStructureHandle(
            ql.BlackConstantVol(to_ql(VALUATION), ql.NullCalendar(), vol, ql.Actual365Fixed())
        ),
    )


def ql_vanilla(option: VanillaOption) -> Any:
    """QuantLib ``VanillaOption`` with the same payoff and exercise style, no engine set."""
    exercise = (
        ql.AmericanExercise(to_ql(VALUATION), to_ql(option.expiry))
        if option.early_exercise
        else ql.EuropeanExercise(to_ql(option.expiry))
    )
    ql_type = ql.Option.Call if option.option_type is OptionType.CALL else ql.Option.Put
    return ql.VanillaOption(ql.PlainVanillaPayoff(ql_type, option.strike), exercise)


def analytic_option(
    option: VanillaOption, spot: float, rates: YieldCurve, dividends: YieldCurve, vol: float
) -> Any:
    """``option`` priced by QuantLib's ``AnalyticEuropeanEngine`` (European exercise)."""
    theirs = ql_vanilla(option)
    theirs.setPricingEngine(ql.AnalyticEuropeanEngine(bsm_process(spot, rates, dividends, vol)))
    return theirs
