from datetime import date

import pytest

from pricer.dates import Schedule, Tenor

SIX_MONTHS = Tenor.parse("6M")


def test_regular_schedule() -> None:
    schedule = Schedule(date(2025, 3, 15), date(2027, 3, 15), SIX_MONTHS)
    assert schedule.dates == (
        date(2025, 3, 15),
        date(2025, 9, 15),
        date(2026, 3, 15),
        date(2026, 9, 15),
        date(2027, 3, 15),
    )
    assert all(p.is_regular for p in schedule)


def test_short_front_stub() -> None:
    schedule = Schedule(date(2025, 5, 1), date(2026, 3, 15), SIX_MONTHS)
    assert schedule.dates == (date(2025, 5, 1), date(2025, 9, 15), date(2026, 3, 15))
    stub, regular = schedule.periods
    assert not stub.is_regular
    assert (stub.ref_start, stub.ref_end) == (date(2025, 3, 15), date(2025, 9, 15))
    assert regular.is_regular


def test_single_period_shorter_than_tenor() -> None:
    schedule = Schedule(date(2025, 8, 29), date(2025, 11, 29), SIX_MONTHS)
    (period,) = schedule.periods
    assert (period.start, period.end) == (date(2025, 8, 29), date(2025, 11, 29))
    assert (period.ref_start, period.ref_end) == (date(2025, 5, 29), date(2025, 11, 29))


def test_first_period_anchored_on_maturity_is_regular_despite_clamping() -> None:
    # 29-Aug-2026 - 6M = 28-Feb-2026 (clamped), but 29-Aug-2026 - 12M = 29-Aug-2025 is the
    # effective date: the first period is regular, not a one-day-short stub.
    # Regression test: QuantLib benchmark caught a 1bp discount error on this case.
    schedule = Schedule(date(2025, 8, 29), date(2026, 8, 29), SIX_MONTHS)
    first, second = schedule.periods
    assert (first.start, first.end) == (date(2025, 8, 29), date(2026, 2, 28))
    assert first.is_regular
    assert second.is_regular


def test_iteration_matches_periods() -> None:
    schedule = Schedule(date(2025, 1, 10), date(2030, 1, 10), Tenor.parse("1Y"))
    assert tuple(schedule) == schedule.periods
    assert len(schedule.periods) == 5


def test_rejects_maturity_before_effective() -> None:
    with pytest.raises(ValueError, match="must be after"):
        Schedule(date(2025, 1, 1), date(2025, 1, 1), SIX_MONTHS)


def test_rejects_zero_tenor() -> None:
    with pytest.raises(ValueError, match="positive"):
        Schedule(date(2025, 1, 1), date(2026, 1, 1), Tenor.parse("0M"))
