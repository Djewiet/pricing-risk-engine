from datetime import date

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pricer.analytics import yield_analytics, yield_times, yield_to_maturity, z_spread
from pricer.engines import discount_bond
from pricer.errors import PricerError
from pricer.instruments import FixedRateBond
from pricer.market import DiscountCurve, FlatForwardCurve, ZeroSpreadedCurve
from pricer.risk import ONE_BP

BOND = FixedRateBond(date(2023, 8, 31), date(2033, 8, 31), 0.0425)
SETTLE = date(2025, 11, 12)


def test_bond_at_its_coupon_rate_prices_at_par_on_coupon_date() -> None:
    # Closed form: if y = c, every period discounts exactly what it pays.
    result = yield_analytics(BOND, 0.0425, date(2025, 8, 31))
    assert result.clean_price == pytest.approx(100.0, abs=1e-12)
    assert result.accrued_interest == 0.0


def test_yield_times_are_whole_periods_after_the_first() -> None:
    _, times = yield_times(BOND, SETTLE)
    first = times[0]
    assert 0.0 < first < 0.5
    assert times[1:-1] - times[:-2] == pytest.approx([0.5] * (len(times) - 2))
    assert times[-1] == times[-2]  # redemption with the last coupon


@given(y=st.floats(min_value=-0.02, max_value=0.3))
def test_price_yield_round_trip(y: float) -> None:
    clean = yield_analytics(BOND, y, SETTLE).clean_price
    assert yield_to_maturity(BOND, clean, SETTLE) == pytest.approx(y, abs=1e-11)


def test_durations_and_convexity_match_finite_differences() -> None:
    y, h = 0.04, 1e-5
    mid = yield_analytics(BOND, y, SETTLE)
    up = yield_analytics(BOND, y + h, SETTLE).dirty_price
    down = yield_analytics(BOND, y - h, SETTLE).dirty_price
    first = (up - down) / (2 * h)
    second = (up - 2 * mid.dirty_price + down) / h**2
    assert mid.modified_duration == pytest.approx(-first / mid.dirty_price, rel=1e-8)
    assert mid.convexity == pytest.approx(second / mid.dirty_price, rel=1e-5)
    assert mid.macaulay_duration == pytest.approx(mid.modified_duration * (1 + y / 2))
    assert mid.dv01 == pytest.approx(mid.modified_duration * mid.dirty_price * ONE_BP)


def test_second_order_taylor_beats_first_order() -> None:
    y, dy = 0.04, 0.01
    base = yield_analytics(BOND, y, SETTLE)
    actual = yield_analytics(BOND, y + dy, SETTLE).dirty_price / base.dirty_price - 1
    first = -base.modified_duration * dy
    second = first + 0.5 * base.convexity * dy**2
    assert abs(second - actual) < abs(first - actual) / 10


def test_single_cash_flow_duration_is_its_time() -> None:
    bond = FixedRateBond(date(2025, 3, 15), date(2026, 3, 15), 0.04)
    result = yield_analytics(bond, 0.04, date(2025, 9, 15))
    assert result.macaulay_duration == pytest.approx(0.5)
    assert result.modified_duration == pytest.approx(0.5 / 1.02)


def test_zero_coupon_bond() -> None:
    bond = FixedRateBond(date(2025, 3, 15), date(2035, 3, 15), 0.0)
    result = yield_analytics(bond, 0.04, date(2025, 3, 15))
    assert result.dirty_price == pytest.approx(100 * 1.02**-20)
    assert result.macaulay_duration == pytest.approx(10.0)


def test_analytics_errors() -> None:
    with pytest.raises(PricerError, match="on or after issue"):
        yield_analytics(BOND, 0.04, date(2023, 1, 1))
    with pytest.raises(PricerError, match="no cash flow"):
        yield_analytics(BOND, 0.04, date(2033, 8, 31))
    with pytest.raises(ValueError, match="greater than -2"):
        yield_analytics(BOND, -2.5, SETTLE)
    with pytest.raises(PricerError, match="No yield"):
        yield_to_maturity(BOND, 1e9, SETTLE)


class TestZSpread:
    curve = DiscountCurve(
        SETTLE,
        [date(2026, 5, 12), date(2027, 11, 12), date(2030, 11, 12), date(2035, 11, 12)],
        [0.98, 0.93, 0.85, 0.68],
    )

    def test_zero_when_priced_on_the_curve(self) -> None:
        clean = discount_bond(BOND, self.curve).clean_price
        assert z_spread(BOND, clean, self.curve) == pytest.approx(0.0, abs=1e-12)

    def test_recovers_a_known_spread(self) -> None:
        clean = discount_bond(BOND, ZeroSpreadedCurve(self.curve, 0.0125)).clean_price
        assert z_spread(BOND, clean, self.curve) == pytest.approx(0.0125, abs=1e-12)

    def test_cheaper_bond_has_higher_spread(self) -> None:
        clean = discount_bond(BOND, self.curve).clean_price
        assert z_spread(BOND, clean - 1.0, self.curve) > 0.0

    def test_unsolvable(self) -> None:
        with pytest.raises(PricerError, match="No z-spread"):
            z_spread(BOND, 10_000.0, FlatForwardCurve(SETTLE, 0.03))
