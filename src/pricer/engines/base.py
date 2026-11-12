"""Pricing engine abstraction (Strategy pattern)."""

from __future__ import annotations

from typing import Protocol

from pricer.market.snapshot import MarketSnapshot


class PricingEngine[InstrumentT, ResultT](Protocol):
    """Computes a result for an instrument from a market snapshot.

    Engines are stateless strategies injected by the caller. Adding a model or a numerical
    method means adding an engine, never modifying an instrument or another engine.
    """

    def price(self, instrument: InstrumentT, market: MarketSnapshot, /) -> ResultT:
        """Value ``instrument`` on ``market``."""
        ...
