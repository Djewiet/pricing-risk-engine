from datetime import date

import pytest

from pricer.dates import (
    ACT_360,
    ACT_365F,
    ACT_ACT_ISDA,
    THIRTY_360,
    ActualActualICMA,
    DayCount,
)


def test_all_conventions_satisfy_protocol() -> None:
    for convention in (ACT_360, ACT_365F, ACT_ACT_ISDA, THIRTY_360, ActualActualICMA(2)):
        assert isinstance(convention, DayCount)
        assert convention.name


def test_actual_conventions() -> None:
    start, end = date(2025, 1, 1), date(2025, 7, 1)  # 181 days
    assert ACT_360.year_fraction(start, end) == pytest.approx(181 / 360)
    assert ACT_365F.year_fraction(start, end) == pytest.approx(181 / 365)
    assert ACT_365F.year_fraction(end, start) == pytest.approx(-181 / 365)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2025, 1, 31), date(2025, 7, 31), 0.5),  # D1=31->30, D2=31->30 since D1=30
        (date(2025, 1, 15), date(2025, 7, 31), (6 * 30 + 16) / 360),  # D2 stays 31
        (date(2025, 2, 28), date(2025, 8, 31), (6 * 30 + 3) / 360),
        (date(2024, 3, 30), date(2025, 3, 31), 1.0),
    ],
)
def test_thirty_360_bond_basis(start: date, end: date, expected: float) -> None:
    assert THIRTY_360.year_fraction(start, end) == pytest.approx(expected)


def test_act_act_isda_splits_leap_years() -> None:
    # ISDA 2006 example: 1-Nov-2003 to 1-May-2004.
    expected = 61 / 365 + 121 / 366
    assert ACT_ACT_ISDA.year_fraction(date(2003, 11, 1), date(2004, 5, 1)) == pytest.approx(
        expected
    )
    assert ACT_ACT_ISDA.year_fraction(date(2024, 2, 1), date(2024, 3, 1)) == pytest.approx(29 / 366)
    assert ACT_ACT_ISDA.year_fraction(date(2023, 1, 1), date(2026, 1, 1)) == pytest.approx(3.0)
    assert ACT_ACT_ISDA.year_fraction(date(2004, 5, 1), date(2003, 11, 1)) == pytest.approx(
        -expected
    )


class TestActualActualICMA:
    icma = ActualActualICMA(2)

    def test_regular_period_is_exactly_one_over_frequency(self) -> None:
        # 181 days or 184 days: a regular semi-annual coupon is always 0.5.
        for start, end in [
            (date(2025, 2, 28), date(2025, 8, 28)),
            (date(2025, 8, 28), date(2026, 2, 28)),
        ]:
            assert self.icma.year_fraction(start, end, start, end) == 0.5

    def test_short_stub(self) -> None:
        ref_start, ref_end = date(2025, 2, 28), date(2025, 8, 28)
        start = date(2025, 6, 1)
        expected = (ref_end - start).days / (2 * (ref_end - ref_start).days)
        assert self.icma.year_fraction(start, ref_end, ref_start, ref_end) == pytest.approx(
            expected
        )

    def test_empty_period(self) -> None:
        assert self.icma.year_fraction(date(2025, 1, 1), date(2025, 1, 1)) == 0.0

    def test_requires_reference_period(self) -> None:
        with pytest.raises(ValueError, match="reference coupon period"):
            self.icma.year_fraction(date(2025, 1, 1), date(2025, 7, 1))

    def test_rejects_long_stub(self) -> None:
        with pytest.raises(ValueError, match="long stubs"):
            self.icma.year_fraction(
                date(2024, 12, 1), date(2025, 7, 1), date(2025, 1, 1), date(2025, 7, 1)
            )

    def test_rejects_non_positive_frequency(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            ActualActualICMA(0)
