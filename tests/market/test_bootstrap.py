import math
import random
from datetime import date

import pytest

from pricer.dates import THIRTY_360, Tenor
from pricer.errors import BootstrapError, MarketDataError
from pricer.market import (
    Compounding,
    FlatForwardCurve,
    ParBondConvention,
    ParYieldQuote,
    bootstrap_par_yield_curve,
    par_yield,
)

REF = date(2025, 8, 29)

TREASURY_LIKE = {
    "1M": 0.0440, "2M": 0.0435, "3M": 0.0430, "4M": 0.0420, "6M": 0.0405,
    "1Y": 0.0385, "2Y": 0.0360, "3Y": 0.0355, "5Y": 0.0365, "7Y": 0.0385,
    "10Y": 0.0420, "20Y": 0.0480, "30Y": 0.0490,
}  # fmt: skip


def quotes(rates: dict[str, float]) -> list[ParYieldQuote]:
    return [ParYieldQuote(Tenor.parse(k), v) for k, v in rates.items()]


def test_curve_reprices_every_input_par_yield() -> None:
    curve = bootstrap_par_yield_curve(REF, quotes(TREASURY_LIKE))
    for tenor, rate in TREASURY_LIKE.items():
        maturity = Tenor.parse(tenor).advance(REF)
        assert par_yield(curve, maturity) == pytest.approx(rate, abs=1e-12)


def test_one_pillar_per_quote_at_maturity() -> None:
    curve = bootstrap_par_yield_curve(REF, quotes(TREASURY_LIKE))
    assert curve.pillar_dates == tuple(Tenor.parse(k).advance(REF) for k in TREASURY_LIKE)


def test_flat_par_curve_gives_geometric_discount_factors() -> None:
    # Closed form: if every semi-annual par yield equals c, then P(n x 6M) = (1 + c/2)^-n,
    # i.e. the semi-annually compounded zero rate is c at every coupon date.
    c = 0.05
    ref = date(2025, 3, 15)  # mid-month: no end-of-month clamping
    tenors = {f"{6 * n}M": c for n in range(1, 21)}
    curve = bootstrap_par_yield_curve(ref, quotes(tenors))
    for n in range(1, 21):
        d = Tenor.parse(f"{6 * n}M").advance(ref)
        assert curve.discount(d) == pytest.approx((1 + c / 2) ** -n, rel=1e-13)


def test_short_end_is_simple_interest() -> None:
    # A bond shorter than one coupon period pays 1 + c * tau at maturity only.
    curve = bootstrap_par_yield_curve(REF, quotes({"3M": 0.04}))
    maturity = date(2025, 11, 29)
    tau = (maturity - REF).days / (2 * (maturity - date(2025, 5, 29)).days)
    assert curve.discount(maturity) == pytest.approx(1 / (1 + 0.04 * tau), rel=1e-13)


def test_quote_order_is_irrelevant() -> None:
    shuffled = quotes(TREASURY_LIKE)
    random.Random(42).shuffle(shuffled)
    a = bootstrap_par_yield_curve(REF, quotes(TREASURY_LIKE))
    b = bootstrap_par_yield_curve(REF, shuffled)
    assert a.pillar_discounts == pytest.approx(b.pillar_discounts, rel=1e-15)


def test_locality_of_log_linear_bootstrap() -> None:
    # Bumping the 10Y quote must not move any pillar before the 7Y-10Y segment.
    base = bootstrap_par_yield_curve(REF, quotes(TREASURY_LIKE))
    bumped = bootstrap_par_yield_curve(REF, quotes({**TREASURY_LIKE, "10Y": 0.0421}))
    for d in base.pillar_dates:
        if d <= Tenor.parse("7Y").advance(REF):
            assert bumped.discount(d) == base.discount(d)
    assert bumped.discount(Tenor.parse("10Y").advance(REF)) < base.discount(
        Tenor.parse("10Y").advance(REF)
    )


def test_negative_rates() -> None:
    curve = bootstrap_par_yield_curve(REF, quotes({"1Y": -0.005, "2Y": -0.003, "5Y": 0.001}))
    assert curve.zero_rate(date(2026, 8, 29)) < 0.0
    assert par_yield(curve, date(2027, 8, 29)) == pytest.approx(-0.003, abs=1e-12)


def test_par_yield_on_flat_forward_curve() -> None:
    # On a flat continuous curve r, a regular semi-annual par yield is 2(e^{r/2} - 1),
    # up to the ACT/365F vs ACT/ACT ICMA time mismatch (< 1bp).
    r = 0.04
    curve = FlatForwardCurve(date(2025, 3, 15), r)
    assert par_yield(curve, date(2035, 3, 15)) == pytest.approx(2 * (math.exp(r / 2) - 1), abs=1e-4)


def test_custom_convention() -> None:
    convention = ParBondConvention(frequency=1, coupon_day_count=THIRTY_360)
    rates = {"1Y": 0.03, "2Y": 0.032, "5Y": 0.035}
    curve = bootstrap_par_yield_curve(REF, quotes(rates), convention)
    assert curve.discount(date(2026, 8, 29)) == pytest.approx(1 / 1.03, rel=1e-13)
    for tenor, rate in rates.items():
        maturity = Tenor.parse(tenor).advance(REF)
        assert par_yield(curve, maturity, convention) == pytest.approx(rate, abs=1e-12)
    assert convention.period == Tenor.parse("12M")
    assert curve.zero_rate(date(2026, 8, 29), Compounding.COMPOUNDED, 1) == pytest.approx(
        0.03, abs=1e-12
    )


def test_rejects_empty_quotes() -> None:
    with pytest.raises(MarketDataError, match="without quotes"):
        bootstrap_par_yield_curve(REF, [])


def test_rejects_duplicate_maturities() -> None:
    with pytest.raises(MarketDataError, match="distinct maturities"):
        bootstrap_par_yield_curve(REF, quotes({"12M": 0.03, "1Y": 0.031}))


def test_unsolvable_quote_raises_bootstrap_error() -> None:
    with pytest.raises(BootstrapError, match="Cannot solve the 2Y pillar"):
        bootstrap_par_yield_curve(REF, quotes({"1Y": 0.03, "2Y": 5.0}))


def test_rejects_non_finite_quote() -> None:
    with pytest.raises(MarketDataError, match="finite"):
        ParYieldQuote(Tenor.parse("1Y"), float("nan"))


@pytest.mark.parametrize("frequency", [0, 5, -2])
def test_convention_rejects_invalid_frequency(frequency: int) -> None:
    with pytest.raises(ValueError, match="divide 12"):
        ParBondConvention(frequency=frequency)
