import math
from datetime import UTC, date, datetime

import pytest

from pricer.errors import MissingMarketDataError, PricerError
from pricer.market import FlatForwardCurve, FlatVolatility, MarketSnapshot
from pricer.models import BlackScholesInputs, BlackScholesModel

VALUATION = date(2025, 11, 12)
EXPIRY = date(2026, 11, 12)  # 365 days: T = 1 on ACT/365F
MARKET = MarketSnapshot(
    timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
    valuation_date=VALUATION,
    curves={
        "USD": FlatForwardCurve(VALUATION, 0.04),
        "SPX-DIV": FlatForwardCurve(VALUATION, 0.015),
    },
    spots={"SPX": 5000.0},
    volatilities={"SPX": FlatVolatility(0.18)},
)


def test_inputs_resolve_market_data() -> None:
    inputs = BlackScholesModel("USD", "SPX-DIV").inputs("SPX", EXPIRY, 5000.0, MARKET)
    assert inputs.spot == 5000.0
    assert inputs.time_to_expiry == 1.0
    assert inputs.discount_factor == pytest.approx(math.exp(-0.04), rel=1e-15)
    assert inputs.dividend_discount_factor == pytest.approx(math.exp(-0.015), rel=1e-15)
    assert inputs.volatility == 0.18
    # Closed form of the forward with flat rates: S exp((r - q) T).
    assert inputs.forward == pytest.approx(5000.0 * math.exp(0.025), rel=1e-15)
    assert inputs.rate == pytest.approx(0.04, rel=1e-14)
    assert inputs.dividend_yield == pytest.approx(0.015, rel=1e-14)
    assert inputs.total_volatility == pytest.approx(0.18, rel=1e-15)


def test_no_dividend_curve_means_zero_yield() -> None:
    inputs = BlackScholesModel("USD").inputs("SPX", EXPIRY, 5000.0, MARKET)
    assert inputs.dividend_discount_factor == 1.0
    assert inputs.dividend_yield == 0.0


def test_rates_are_zero_at_expiry() -> None:
    # T = 0: the zero rate is undefined; report 0 so that theta stays finite.
    inputs = BlackScholesInputs(100.0, 0.0, 1.0, 1.0, 0.2)
    assert inputs.rate == 0.0
    assert inputs.dividend_yield == 0.0
    assert inputs.total_volatility == 0.0


def test_rejects_expired_option() -> None:
    with pytest.raises(PricerError, match="before the valuation date"):
        BlackScholesModel("USD").inputs("SPX", date(2025, 11, 11), 5000.0, MARKET)


@pytest.mark.parametrize(
    ("model", "underlying"),
    [
        (BlackScholesModel("EUR"), "SPX"),
        (BlackScholesModel("USD", "NDX-DIV"), "SPX"),
        (BlackScholesModel("USD"), "NDX"),
    ],
)
def test_missing_market_data(model: BlackScholesModel, underlying: str) -> None:
    with pytest.raises(MissingMarketDataError):
        model.inputs(underlying, EXPIRY, 5000.0, MARKET)
