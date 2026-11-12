import math
from datetime import date

import numpy as np
import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from pricer.dates import ACT_360, ACT_365F
from pricer.errors import MarketDataError
from pricer.market import (
    Compounding,
    DiscountCurve,
    FlatForwardCurve,
    ZeroSpreadedCurve,
    discount_from_rate,
    rate_from_discount,
)

REF = date(2025, 8, 29)

rates = st.floats(min_value=-0.05, max_value=0.5)
times = st.floats(min_value=1e-3, max_value=50.0)
compoundings = st.sampled_from(list(Compounding))
frequencies = st.sampled_from([1, 2, 4, 12])


class TestRateConversions:
    @given(rate=rates, t=times, compounding=compoundings, frequency=frequencies)
    def test_round_trip(
        self, rate: float, t: float, compounding: Compounding, frequency: int
    ) -> None:
        assume(compounding is not Compounding.SIMPLE or 1.0 + rate * t > 1e-3)
        discount = discount_from_rate(rate, t, compounding, frequency)
        assert rate_from_discount(discount, t, compounding, frequency) == pytest.approx(
            rate, abs=1e-10
        )

    def test_known_values(self) -> None:
        assert discount_from_rate(0.05, 2.0) == pytest.approx(math.exp(-0.1))
        assert discount_from_rate(0.05, 0.5, Compounding.SIMPLE) == pytest.approx(1 / 1.025)
        assert discount_from_rate(0.05, 2.0, Compounding.COMPOUNDED, 2) == pytest.approx(1.025**-4)

    def test_continuous_rate_below_compounded(self) -> None:
        # Compounding more often needs a lower rate for the same discount factor.
        d = 0.9
        annual = rate_from_discount(d, 2.0, Compounding.COMPOUNDED, 1)
        semi = rate_from_discount(d, 2.0, Compounding.COMPOUNDED, 2)
        cont = rate_from_discount(d, 2.0)
        assert annual > semi > cont

    @pytest.mark.parametrize(
        ("discount", "t", "frequency", "match"),
        [
            (0.9, 0.0, 1, "t > 0"),
            (0.0, 1.0, 1, "positive"),
            (0.9, 1.0, 0, "frequency"),
        ],
    )
    def test_rate_from_discount_rejects(
        self, discount: float, t: float, frequency: int, match: str
    ) -> None:
        with pytest.raises(ValueError, match=match):
            rate_from_discount(discount, t, Compounding.COMPOUNDED, frequency)

    def test_discount_from_rate_rejects_non_positive_growth(self) -> None:
        with pytest.raises(ValueError, match="growth factor"):
            discount_from_rate(-0.5, 2.0, Compounding.SIMPLE)
        with pytest.raises(ValueError, match="greater than -2"):
            discount_from_rate(-2.0, 1.0, Compounding.COMPOUNDED, 2)

    def test_discount_from_rate_rejects_bad_frequency(self) -> None:
        with pytest.raises(ValueError, match="frequency"):
            discount_from_rate(0.05, 1.0, Compounding.COMPOUNDED, 0)


class TestFlatForwardCurve:
    curve = FlatForwardCurve(REF, 0.03)

    def test_discount(self) -> None:
        d = date(2027, 8, 29)
        t = (d - REF).days / 365
        assert self.curve.discount(d) == pytest.approx(math.exp(-0.03 * t))
        assert self.curve.discount(REF) == 1.0

    def test_zero_and_forward_rates_are_flat(self) -> None:
        assert self.curve.zero_rate(date(2030, 1, 1)) == pytest.approx(0.03)
        assert self.curve.forward_rate(date(2026, 1, 1), date(2031, 1, 1)) == pytest.approx(0.03)

    def test_vectorised(self) -> None:
        t = np.array([0.0, 1.0, 10.0])
        np.testing.assert_allclose(self.curve.discount_factors(t), np.exp(-0.03 * t))

    def test_rejects_negative_time(self) -> None:
        with pytest.raises(ValueError, match="t >= 0"):
            self.curve.discount_factor(-0.1)

    def test_day_count_is_explicit(self) -> None:
        curve = FlatForwardCurve(REF, 0.03, ACT_360)
        assert curve.day_count is ACT_360
        assert curve.reference_date == REF
        assert curve.time(date(2025, 9, 28)) == pytest.approx(30 / 360)


class TestDiscountCurve:
    dates = (date(2026, 8, 29), date(2027, 8, 29), date(2030, 8, 29))
    discounts = (0.96, 0.925, 0.82)
    curve = DiscountCurve(REF, dates, discounts)

    def test_exact_at_pillars(self) -> None:
        for d, p in zip(self.dates, self.discounts, strict=True):
            assert self.curve.discount(d) == pytest.approx(p, rel=1e-14)
        assert self.curve.discount(REF) == 1.0

    def test_log_linear_midpoint_is_geometric_mean(self) -> None:
        t1, t2 = self.curve.pillar_times[:2]
        mid = self.curve.discount_factor(0.5 * (t1 + t2))
        assert mid == pytest.approx(math.sqrt(0.96 * 0.925), rel=1e-14)

    def test_forward_is_piecewise_constant(self) -> None:
        f1 = self.curve.forward_rate(date(2027, 9, 1), date(2028, 3, 1))
        f2 = self.curve.forward_rate(date(2028, 3, 1), date(2030, 8, 1))
        t2, t3 = self.curve.pillar_times[1:]
        expected = math.log(0.925 / 0.82) / (t3 - t2)
        assert f1 == pytest.approx(expected, rel=1e-12)
        assert f2 == pytest.approx(expected, rel=1e-12)

    def test_first_segment_starts_from_one(self) -> None:
        t1 = self.curve.pillar_times[0]
        assert self.curve.zero_rate(date(2026, 2, 1)) == pytest.approx(-math.log(0.96) / t1)

    def test_flat_forward_extrapolation(self) -> None:
        t2, t3 = self.curve.pillar_times[1:]
        last_forward = math.log(0.925 / 0.82) / (t3 - t2)
        far = self.curve.forward_rate(date(2035, 1, 1), date(2045, 1, 1))
        assert far == pytest.approx(last_forward, rel=1e-12)

    def test_single_pillar_is_flat(self) -> None:
        curve = DiscountCurve(REF, [date(2026, 8, 29)], [0.97])
        z = curve.zero_rate(date(2026, 8, 29))
        assert curve.zero_rate(date(2040, 1, 1)) == pytest.approx(z)
        assert curve.zero_rate(date(2025, 12, 1)) == pytest.approx(z)

    def test_monotone_for_positive_rates(self) -> None:
        t = np.linspace(0.0, 40.0, 2001)
        assert np.all(np.diff(self.curve.discount_factors(t)) < 0.0)

    def test_negative_rates_are_supported(self) -> None:
        curve = DiscountCurve(REF, [date(2026, 8, 29)], [1.005])
        assert curve.zero_rate(date(2026, 8, 29)) < 0.0

    def test_immutable(self) -> None:
        with pytest.raises(AttributeError):
            self.curve.reference = date(2020, 1, 1)  # type: ignore[misc]
        with pytest.raises(ValueError, match="read-only"):
            self.curve.pillar_times[0] = 0.0

    def test_input_order_matters(self) -> None:
        assert self.curve.pillar_dates == self.dates
        assert self.curve.day_count is ACT_365F

    @pytest.mark.parametrize(
        ("dates", "discounts", "match"),
        [
            ([date(2026, 1, 1)], [0.9, 0.8], "pillar dates but"),
            ([], [], "at least one"),
            ([REF], [0.99], "after the reference"),
            ([date(2027, 1, 1), date(2026, 1, 1)], [0.9, 0.95], "strictly increasing"),
            ([date(2026, 1, 1), date(2026, 1, 1)], [0.9, 0.9], "strictly increasing"),
            ([date(2026, 1, 1)], [0.0], "positive"),
            ([date(2026, 1, 1)], [math.nan], "finite"),
        ],
    )
    def test_validation(self, dates: list[date], discounts: list[float], match: str) -> None:
        with pytest.raises(MarketDataError, match=match):
            DiscountCurve(REF, dates, discounts)


class TestZeroSpreadedCurve:
    base = DiscountCurve(REF, [date(2026, 8, 29), date(2030, 8, 29)], [0.96, 0.82])

    def test_shifts_every_zero_rate(self) -> None:
        shifted = ZeroSpreadedCurve(self.base, 0.01)
        for d in (date(2026, 1, 1), date(2028, 6, 30), date(2040, 1, 1)):
            assert shifted.zero_rate(d) == pytest.approx(self.base.zero_rate(d) + 0.01)
        assert shifted.forward_rate(date(2027, 1, 1), date(2029, 1, 1)) == pytest.approx(
            self.base.forward_rate(date(2027, 1, 1), date(2029, 1, 1)) + 0.01
        )

    def test_inherits_anchor_and_axis(self) -> None:
        shifted = ZeroSpreadedCurve(self.base, -0.002)
        assert shifted.reference_date == REF
        assert shifted.day_count is self.base.day_count
        assert shifted.discount(REF) == 1.0
