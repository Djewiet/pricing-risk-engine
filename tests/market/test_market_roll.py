from datetime import UTC, date, datetime

import numpy as np
import pytest

from pricer.dates import ACT_360, Tenor
from pricer.errors import MarketDataError
from pricer.market import (
    FlatForwardCurve,
    FlatVolatility,
    MarketSnapshot,
    ParYieldQuote,
    RolledCurve,
    ShiftedVolatility,
    bootstrap_par_yield_curve,
)

REF = date(2025, 11, 12)
CURVE = bootstrap_par_yield_curve(
    REF,
    [
        ParYieldQuote(Tenor.parse(t), r)
        for t, r in {"3M": 0.043, "1Y": 0.0385, "2Y": 0.036, "5Y": 0.0365, "10Y": 0.042}.items()
    ],
)


def test_rolled_curve_keeps_forward_rates() -> None:
    # Tomorrow's curve is today's forward curve: every forward between two later dates is
    # unchanged, while zero rates to a fixed date move (roll-down).
    rolled = RolledCurve(CURVE, date(2026, 2, 12))
    assert rolled.reference_date == date(2026, 2, 12)
    assert rolled.discount(date(2026, 2, 12)) == pytest.approx(1.0, abs=1e-16)
    for start, end in [(date(2026, 5, 1), date(2027, 1, 4)), (date(2028, 3, 1), date(2034, 1, 1))]:
        assert rolled.forward_rate(start, end) == pytest.approx(
            CURVE.forward_rate(start, end), rel=1e-12
        )
    assert rolled.zero_rate(date(2030, 1, 1)) != pytest.approx(CURVE.zero_rate(date(2030, 1, 1)))
    # Closed form: P'(d) = P(d) / P(new reference).
    d = date(2031, 6, 30)
    assert rolled.discount(d) == pytest.approx(
        CURVE.discount(d) / CURVE.discount(date(2026, 2, 12)), rel=1e-14
    )


def test_rolled_flat_curve_is_the_same_flat_curve() -> None:
    rolled = RolledCurve(FlatForwardCurve(REF, 0.03, ACT_360), date(2026, 1, 1))
    assert rolled.day_count is ACT_360
    times = np.array([0.0, 0.5, 7.0])
    np.testing.assert_allclose(rolled.discount_factors(times), np.exp(-0.03 * times), rtol=1e-15)


def test_rolled_curve_rejects_rolling_back_and_negative_times() -> None:
    with pytest.raises(MarketDataError, match="back"):
        RolledCurve(CURVE, date(2025, 11, 11))
    with pytest.raises(ValueError, match="t >= 0"):
        RolledCurve(CURVE, date(2026, 1, 1)).discount_factors(np.array([-0.1]))


def test_shifted_volatility() -> None:
    surface = ShiftedVolatility(FlatVolatility(0.2), 0.01)
    assert surface.black_vol(1.0, 100.0) == pytest.approx(0.21)
    with pytest.raises(MarketDataError, match="negative"):
        ShiftedVolatility(FlatVolatility(0.2), -0.3).black_vol(1.0, 100.0)


def test_snapshot_roll_forward() -> None:
    market = MarketSnapshot(
        timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
        valuation_date=REF,
        curves={"USD": CURVE},
        spots={"SPX": 5000.0},
        volatilities={"SPX": FlatVolatility(0.2)},
    )
    later = market.roll_forward(3)
    assert later.valuation_date == date(2025, 11, 15)
    assert later.timestamp == datetime(2025, 11, 15, 21, 0, tzinfo=UTC)
    assert later.curve("USD").reference_date == date(2025, 11, 15)
    assert later.spots == market.spots
    assert later.volatilities == market.volatilities
    assert market.curve("USD") is CURVE  # the base snapshot is untouched
    assert market.roll_forward(0).curve("USD").discount(date(2030, 1, 2)) == pytest.approx(
        CURVE.discount(date(2030, 1, 2)), rel=1e-15
    )
    with pytest.raises(ValueError, match="backwards"):
        market.roll_forward(-1)
