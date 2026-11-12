import math
from datetime import UTC, date, datetime

import pytest

from pricer.analytics import yield_analytics, yield_to_maturity
from pricer.engines import DiscountingBondEngine
from pricer.instruments import FixedRateBond
from pricer.market import FlatForwardCurve, MarketSnapshot
from pricer.risk import ONE_BP, parallel_dv01

REF = date(2025, 8, 29)
MARKET = MarketSnapshot(
    datetime(2025, 8, 29, 21, tzinfo=UTC), REF, curves={"UST": FlatForwardCurve(REF, 0.04)}
)
ENGINE = DiscountingBondEngine("UST")


def test_zero_coupon_dv01_is_time_times_price() -> None:
    # dP/ds = -t P for a continuously-compounded shift: closed form.
    bond = FixedRateBond(REF, date(2035, 8, 29), 0.0)
    t = (date(2035, 8, 29) - REF).days / 365
    dv01 = parallel_dv01(lambda m: ENGINE.price(bond, m).npv, MARKET, "UST")
    # Central difference error is (h t)^2 / 6 in relative terms: ~1.7e-7 here.
    assert dv01 == pytest.approx(t * 100 * math.exp(-0.04 * t) * ONE_BP, rel=(ONE_BP * t) ** 2)


def test_curve_dv01_is_close_to_yield_dv01() -> None:
    # Both measure a 1bp move, but on different rates (continuous zeros vs semi-annual
    # yield): they agree to about y/2 in relative terms.
    bond = FixedRateBond(date(2024, 2, 29), date(2034, 2, 28), 0.045)
    curve_dv01 = parallel_dv01(lambda m: ENGINE.price(bond, m).dirty_price, MARKET, "UST")
    clean = ENGINE.price(bond, MARKET).clean_price
    y = yield_to_maturity(bond, clean, REF)
    assert curve_dv01 == pytest.approx(yield_analytics(bond, y, REF).dv01, rel=0.03)


def test_bump_size_is_normalised_and_base_untouched() -> None:
    bond = FixedRateBond(REF, date(2030, 8, 29), 0.04)

    def value(m: MarketSnapshot) -> float:
        return ENGINE.price(bond, m).npv

    small = parallel_dv01(value, MARKET, "UST")
    large = parallel_dv01(value, MARKET, "UST", bump=10 * ONE_BP)
    assert large == pytest.approx(small, rel=1e-4)
    assert isinstance(MARKET.curve("UST"), FlatForwardCurve)
