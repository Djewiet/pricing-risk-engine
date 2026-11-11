from datetime import date

import pytest

from pricer.dates import Tenor, TenorUnit, add_months


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2025, 1, 15), 1, date(2025, 2, 15)),
        (date(2025, 1, 31), 1, date(2025, 2, 28)),
        (date(2024, 1, 31), 1, date(2024, 2, 29)),
        (date(2025, 2, 28), 1, date(2025, 3, 28)),
        (date(2025, 11, 30), 3, date(2026, 2, 28)),
        (date(2025, 3, 31), -1, date(2025, 2, 28)),
        (date(2025, 1, 10), -13, date(2023, 12, 10)),
        (date(2025, 8, 29), 0, date(2025, 8, 29)),
    ],
)
def test_add_months_clamps_to_month_end(start: date, months: int, expected: date) -> None:
    assert add_months(start, months) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("6M", Tenor(6, TenorUnit.MONTHS)),
        ("10y", Tenor(10, TenorUnit.YEARS)),
        (" 6 W ", Tenor(6, TenorUnit.WEEKS)),
        ("1D", Tenor(1, TenorUnit.DAYS)),
    ],
)
def test_parse(text: str, expected: Tenor) -> None:
    assert Tenor.parse(text) == expected


@pytest.mark.parametrize("text", ["", "M", "6", "1.5M", "-1Y", "3Q"])
def test_parse_rejects_invalid(text: str) -> None:
    with pytest.raises(ValueError, match="Invalid tenor"):
        Tenor.parse(text)


def test_negative_length_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        Tenor(-1, TenorUnit.MONTHS)


@pytest.mark.parametrize(
    ("tenor", "times", "expected"),
    [
        ("1D", 1, date(2025, 9, 1)),
        ("2W", 1, date(2025, 9, 14)),
        ("6M", 1, date(2026, 2, 28)),
        ("1Y", 1, date(2026, 8, 31)),
        ("6M", -2, date(2024, 8, 31)),
        ("6M", -1, date(2025, 2, 28)),
    ],
)
def test_advance(tenor: str, times: int, expected: date) -> None:
    assert Tenor.parse(tenor).advance(date(2025, 8, 31), times) == expected


def test_advance_in_one_step_avoids_day_drift() -> None:
    tenor = Tenor.parse("6M")
    stepwise = tenor.advance(tenor.advance(date(2025, 8, 31), -1), -1)
    assert stepwise == date(2024, 8, 28)
    assert tenor.advance(date(2025, 8, 31), -2) == date(2024, 8, 31)


def test_str_round_trips() -> None:
    assert str(Tenor.parse("30Y")) == "30Y"
