from datetime import date

import pytest

from pricer.dates import THIRTY_360, Tenor
from pricer.instruments import InterestRateSwap, OvernightCoupon, SwapDirection

SWAP = InterestRateSwap(date(2025, 3, 17), date(2028, 3, 17), 0.04, notional=10_000_000.0)


def test_default_conventions_are_usd_sofr_ois() -> None:
    assert [c.payment_date for c in SWAP.fixed_leg] == [
        date(2026, 3, 17),
        date(2027, 3, 17),
        date(2028, 3, 17),
    ]
    first = SWAP.fixed_leg[0]
    assert first.accrual == pytest.approx(365 / 360)
    assert first.amount == pytest.approx(10_000_000 * 0.04 * 365 / 360)
    assert SWAP.direction is SwapDirection.PAYER


def test_floating_leg_mirrors_schedule() -> None:
    assert SWAP.floating_leg[1] == OvernightCoupon(
        payment_date=date(2027, 3, 17),
        nominal=10_000_000.0,
        accrual_start=date(2026, 3, 17),
        accrual_end=date(2027, 3, 17),
        accrual=365 / 360,
        spread=0.0,
    )


def test_legs_can_have_different_frequencies_and_conventions() -> None:
    swap = InterestRateSwap(
        date(2025, 1, 15),
        date(2030, 1, 15),
        0.035,
        fixed_tenor=Tenor.parse("6M"),
        fixed_day_count=THIRTY_360,
        floating_tenor=Tenor.parse("3M"),
        floating_spread=0.001,
    )
    assert len(swap.fixed_leg) == 10
    assert len(swap.floating_leg) == 20
    assert all(c.accrual == 0.5 for c in swap.fixed_leg)
    assert all(c.spread == 0.001 for c in swap.floating_leg)


def test_short_front_stub_on_both_legs() -> None:
    swap = InterestRateSwap(date(2025, 5, 1), date(2027, 3, 17), 0.04)
    assert swap.fixed_leg[0].accrual_end == date(2026, 3, 17)
    assert swap.floating_leg[0].accrual == pytest.approx(
        (date(2026, 3, 17) - date(2025, 5, 1)).days / 360
    )


def test_direction_sign() -> None:
    assert SwapDirection.PAYER.sign == 1
    assert SwapDirection.RECEIVER.sign == -1


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"fixed_rate": float("nan")}, "fixed_rate must be finite"),
        ({"floating_spread": float("inf")}, "floating_spread must be finite"),
        ({"notional": -1.0}, "Notional"),
        ({"maturity": date(2025, 3, 17)}, "must be after"),
        ({"floating_tenor": Tenor.parse("0M")}, "positive"),
    ],
)
def test_validation(kwargs: dict[str, object], match: str) -> None:
    terms: dict[str, object] = {
        "effective_date": date(2025, 3, 17),
        "maturity": date(2028, 3, 17),
        "fixed_rate": 0.04,
    }
    with pytest.raises(ValueError, match=match):
        InterestRateSwap(**{**terms, **kwargs})  # type: ignore[arg-type]
