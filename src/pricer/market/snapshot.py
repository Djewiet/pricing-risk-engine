"""Immutable, timestamped market snapshot: the single market input of every pricing call.

Passing one immutable object instead of reading market data from globals gives three
guarantees the risk service relies on:

* **reproducibility**: a price is a pure function of (instrument, model, engine, snapshot),
  so any result can be recomputed from the persisted snapshot;
* **thread and process safety**: a snapshot can be shared between workers without locks;
* **consistent risk**: bump-and-revalue Greeks build a *new* bumped snapshot with
  :meth:`MarketSnapshot.with_spot` and friends, so the base scenario can never be corrupted.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from types import MappingProxyType

from pricer.errors import MarketDataError, MissingMarketDataError
from pricer.market.curves import YieldCurve
from pricer.market.volatility import VolatilitySurface


def _frozen[V](mapping: Mapping[str, V]) -> Mapping[str, V]:
    return MappingProxyType(dict(mapping))


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Market data observed at a point in time.

    Keys are free-form identifiers chosen by the caller (``"USD-TSY"`` for a curve,
    ``"AAPL"`` for an equity), used consistently by instruments.

    Snapshots compare by value but are not hashable (their contents are mappings).

    Attributes:
        timestamp: Observation time; must be timezone-aware.
        valuation_date: Pricing date; every curve must be anchored on it.
        curves: Discount curves by identifier.
        spots: Spot prices by underlying identifier; all strictly positive.
        volatilities: Volatility surfaces by underlying identifier.
    """

    timestamp: datetime
    valuation_date: date
    curves: Mapping[str, YieldCurve] = field(default_factory=dict)
    spots: Mapping[str, float] = field(default_factory=dict)
    volatilities: Mapping[str, VolatilitySurface] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            msg = "MarketSnapshot.timestamp must be timezone-aware"
            raise MarketDataError(msg)
        for name, curve in self.curves.items():
            if curve.reference_date != self.valuation_date:
                msg = (
                    f"Curve {name!r} is anchored on {curve.reference_date}, "
                    f"not on the valuation date {self.valuation_date}"
                )
                raise MarketDataError(msg)
        for name, spot in self.spots.items():
            if not (math.isfinite(spot) and spot > 0.0):
                msg = f"Spot {name!r} must be finite and positive, got {spot}"
                raise MarketDataError(msg)
        # Defensive copies behind read-only views: mutating the caller's dicts afterwards
        # must not change the snapshot.
        object.__setattr__(self, "curves", _frozen(self.curves))
        object.__setattr__(self, "spots", _frozen({k: float(v) for k, v in self.spots.items()}))
        object.__setattr__(self, "volatilities", _frozen(self.volatilities))

    __hash__ = None  # type: ignore[assignment]

    def curve(self, name: str) -> YieldCurve:
        """Return the curve ``name``.

        Raises:
            MissingMarketDataError: If the snapshot has no such curve.
        """
        return _lookup(self.curves, name, "curve")

    def spot(self, name: str) -> float:
        """Return the spot price of ``name``.

        Raises:
            MissingMarketDataError: If the snapshot has no such spot.
        """
        return _lookup(self.spots, name, "spot")

    def volatility(self, name: str) -> VolatilitySurface:
        """Return the volatility surface of ``name``.

        Raises:
            MissingMarketDataError: If the snapshot has no such volatility.
        """
        return _lookup(self.volatilities, name, "volatility")

    def with_curve(self, name: str, curve: YieldCurve) -> MarketSnapshot:
        """Return a copy with curve ``name`` added or replaced."""
        return replace(self, curves={**self.curves, name: curve})

    def with_spot(self, name: str, spot: float) -> MarketSnapshot:
        """Return a copy with spot ``name`` added or replaced."""
        return replace(self, spots={**self.spots, name: spot})

    def with_volatility(self, name: str, surface: VolatilitySurface) -> MarketSnapshot:
        """Return a copy with volatility ``name`` added or replaced."""
        return replace(self, volatilities={**self.volatilities, name: surface})


def _lookup[V](mapping: Mapping[str, V], name: str, kind: str) -> V:
    try:
        return mapping[name]
    except KeyError:
        available = ", ".join(sorted(mapping)) or "none"
        msg = f"No {kind} {name!r} in market snapshot (available: {available})"
        raise MissingMarketDataError(msg) from None
