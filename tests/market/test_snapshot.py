from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from pricer.errors import MarketDataError, MissingMarketDataError, PricerError
from pricer.market import FlatForwardCurve, FlatVolatility, MarketSnapshot, VolatilitySurface

VAL = date(2025, 8, 29)
TS = datetime(2025, 8, 29, 21, 0, tzinfo=UTC)


def make_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=TS,
        valuation_date=VAL,
        curves={"USD": FlatForwardCurve(VAL, 0.04)},
        spots={"SPX": 6450.0},
        volatilities={"SPX": FlatVolatility(0.18)},
    )


def test_lookups() -> None:
    snap = make_snapshot()
    assert snap.spot("SPX") == 6450.0
    assert snap.curve("USD").discount(VAL) == 1.0
    assert snap.volatility("SPX").black_vol(1.0, 6000.0) == 0.18


@pytest.mark.parametrize("kind", ["curve", "spot", "volatility"])
def test_missing_data_raises_library_error(kind: str) -> None:
    snap = make_snapshot()
    with pytest.raises(MissingMarketDataError, match=f"No {kind} 'XXX'") as info:
        getattr(snap, kind)("XXX")
    assert isinstance(info.value, PricerError)
    assert isinstance(info.value, KeyError)


def test_missing_message_lists_available_keys() -> None:
    empty = MarketSnapshot(TS, VAL)
    with pytest.raises(MissingMarketDataError, match="available: none"):
        empty.spot("SPX")


def test_frozen_and_defensively_copied() -> None:
    spots = {"SPX": 6450.0}
    snap = MarketSnapshot(TS, VAL, spots=spots)
    spots["SPX"] = 1.0
    assert snap.spot("SPX") == 6450.0
    with pytest.raises(TypeError):
        snap.spots["SPX"] = 1.0  # type: ignore[index]
    with pytest.raises(AttributeError):
        snap.valuation_date = date(2020, 1, 1)  # type: ignore[misc]


def test_with_methods_return_new_snapshot() -> None:
    base = make_snapshot()
    bumped = base.with_spot("SPX", 6451.0)
    assert bumped.spot("SPX") == 6451.0
    assert base.spot("SPX") == 6450.0
    assert bumped.timestamp == base.timestamp

    new_curve = FlatForwardCurve(VAL, 0.05)
    assert base.with_curve("EUR", new_curve).curve("EUR") is new_curve
    assert base.with_volatility("NDX", FlatVolatility(0.2)).volatility("NDX").black_vol(1, 1) == 0.2


def test_value_equality_but_not_hashable() -> None:
    assert make_snapshot().with_spot("SPX", 6450.0).spots == make_snapshot().spots
    with pytest.raises(TypeError):
        hash(make_snapshot())


def test_requires_timezone_aware_timestamp() -> None:
    with pytest.raises(MarketDataError, match="timezone-aware"):
        MarketSnapshot(datetime(2025, 8, 29, 21, 0), VAL)  # noqa: DTZ001


def test_accepts_non_utc_timezone() -> None:
    paris = timezone(timedelta(hours=2))
    assert MarketSnapshot(datetime(2025, 8, 29, 23, 0, tzinfo=paris), VAL).timestamp == TS


def test_rejects_curve_anchored_elsewhere() -> None:
    with pytest.raises(MarketDataError, match="not on the valuation date"):
        MarketSnapshot(TS, VAL, curves={"USD": FlatForwardCurve(date(2025, 8, 28), 0.04)})


@pytest.mark.parametrize("spot", [0.0, -1.0, float("inf"), float("nan")])
def test_rejects_invalid_spot(spot: float) -> None:
    with pytest.raises(MarketDataError, match="finite and positive"):
        MarketSnapshot(TS, VAL, spots={"SPX": spot})


@pytest.mark.parametrize("sigma", [-0.1, float("nan")])
def test_flat_volatility_validation(sigma: float) -> None:
    with pytest.raises(MarketDataError):
        FlatVolatility(sigma)


def test_flat_volatility_satisfies_protocol() -> None:
    assert isinstance(FlatVolatility(0.2), VolatilitySurface)
