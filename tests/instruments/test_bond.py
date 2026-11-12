from datetime import date

import pytest

from pricer.dates import THIRTY_360, ActualActualICMA
from pricer.instruments import FixedCoupon, FixedRateBond, Redemption

BOND = FixedRateBond(date(2025, 3, 15), date(2027, 3, 15), 0.05)


def test_regular_coupons_pay_rate_over_frequency() -> None:
    assert [c.payment_date for c in BOND.coupons] == [
        date(2025, 9, 15),
        date(2026, 3, 15),
        date(2026, 9, 15),
        date(2027, 3, 15),
    ]
    for coupon in BOND.coupons:
        assert coupon.amount == pytest.approx(2.5, rel=1e-15)
        assert coupon.accrual == 0.5


def test_cashflows_end_with_redemption() -> None:
    *coupons, redemption = BOND.cashflows
    assert all(isinstance(c, FixedCoupon) for c in coupons)
    assert redemption == Redemption(date(2027, 3, 15), 100.0)


def test_short_first_coupon() -> None:
    bond = FixedRateBond(date(2025, 5, 1), date(2027, 3, 15), 0.05)
    first = bond.coupons[0]
    assert (first.accrual_start, first.payment_date) == (date(2025, 5, 1), date(2025, 9, 15))
    expected = (date(2025, 9, 15) - date(2025, 5, 1)).days / (2 * 184)
    assert first.accrual == pytest.approx(expected)
    assert first.amount == pytest.approx(100 * 0.05 * expected)


def test_accrued_interest() -> None:
    # 15-Mar to 15-Sep 2025 is 184 days; 15-Mar to 15-Jun is 92 days.
    assert BOND.accrued_interest(date(2025, 6, 15)) == pytest.approx(2.5 * 92 / 184)
    assert BOND.accrued_interest(date(2025, 9, 15)) == 0.0  # coupon date
    assert BOND.accrued_interest(date(2025, 3, 15)) == 0.0  # issue date
    assert BOND.accrued_interest(date(2025, 1, 1)) == 0.0  # before issue
    assert BOND.accrued_interest(date(2028, 1, 1)) == 0.0  # after maturity


def test_accrued_scales_with_face_but_quote_does_not() -> None:
    big = FixedRateBond(date(2025, 3, 15), date(2027, 3, 15), 0.05, face_amount=1_000_000.0)
    settle = date(2025, 6, 15)
    assert big.accrued_amount(settle) == pytest.approx(10_000 * BOND.accrued_amount(settle))
    assert big.accrued_interest(settle) == pytest.approx(BOND.accrued_interest(settle))


def test_remaining_cashflows_exclude_settlement_date_flow() -> None:
    remaining = BOND.remaining_cashflows(date(2025, 9, 15))
    assert remaining[0].payment_date == date(2026, 3, 15)
    assert len(remaining) == 4  # 3 coupons + redemption
    assert BOND.remaining_cashflows(date(2027, 3, 15)) == ()
    assert BOND.is_expired(date(2027, 3, 15))
    assert not BOND.is_expired(date(2027, 3, 14))


def test_explicit_day_count_and_frequency() -> None:
    bond = FixedRateBond(date(2025, 1, 31), date(2028, 1, 31), 0.04, 1, THIRTY_360)
    assert bond.accrual_day_count is THIRTY_360
    assert [c.amount for c in bond.coupons] == pytest.approx([4.0, 4.0, 4.0])
    assert FixedRateBond(date(2025, 1, 1), date(2026, 1, 1), 0.04).accrual_day_count == (
        ActualActualICMA(2)
    )


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"frequency": 5}, "divide 12"),
        ({"frequency": 0}, "divide 12"),
        ({"coupon_rate": float("nan")}, "finite"),
        ({"face_amount": 0.0}, "positive"),
        ({"maturity": date(2025, 3, 15)}, "must be after"),
    ],
)
def test_validation(kwargs: dict[str, object], match: str) -> None:
    terms: dict[str, object] = {
        "issue_date": date(2025, 3, 15),
        "maturity": date(2027, 3, 15),
        "coupon_rate": 0.05,
    }
    with pytest.raises(ValueError, match=match):
        FixedRateBond(**{**terms, **kwargs})  # type: ignore[arg-type]


def test_immutable() -> None:
    with pytest.raises(AttributeError):
        BOND.coupon_rate = 0.06  # type: ignore[misc]
