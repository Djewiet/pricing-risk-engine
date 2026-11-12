"""End-to-end example: price a SOFR-style swap on the bootstrapped Treasury curve.

Phase 1 uses the Treasury curve for both curve roles (forecast and discount), because no
free SOFR swap curve is published; the engine keeps the two roles separate so a SOFR curve
can be plugged in by name. Runs offline on the same quotes as ``price_bond.py``.

Run it with ``uv run python examples/price_swap.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pricer.dates import Tenor
from pricer.engines import DiscountingSwapEngine
from pricer.instruments import InterestRateSwap, SwapDirection
from pricer.market import MarketSnapshot, ParYieldQuote, bootstrap_par_yield_curve
from pricer.risk import parallel_dv01

VALUATION_DATE = date(2025, 12, 31)
CURVE = "USD-TSY"

#: Par yields in percent, by tenor (same as ``price_bond.py``).
QUOTES = {
    "1M": 3.74,
    "3M": 3.67,
    "6M": 3.58,
    "1Y": 3.47,
    "2Y": 3.47,
    "3Y": 3.55,
    "5Y": 3.73,
    "7Y": 3.94,
    "10Y": 4.17,
    "20Y": 4.79,
    "30Y": 4.84,
}


def main() -> None:
    """Run the example and print the results."""
    quotes = [ParYieldQuote(Tenor.parse(t), r / 100.0) for t, r in QUOTES.items()]
    snapshot = MarketSnapshot(
        timestamp=datetime(2025, 12, 31, 21, 0, tzinfo=UTC),
        valuation_date=VALUATION_DATE,
        curves={CURVE: bootstrap_par_yield_curve(VALUATION_DATE, quotes)},
    )
    # Both curve roles point to the Treasury curve in phase 1.
    engine = DiscountingSwapEngine(discount_curve=CURVE, forecast_curve=CURVE)

    # A 10Y payer swap: pay 4% fixed, receive compounded overnight, 10mm notional.
    swap = InterestRateSwap(
        effective_date=VALUATION_DATE,
        maturity=date(2035, 12, 31),
        fixed_rate=0.04,
        notional=10_000_000.0,
        direction=SwapDirection.PAYER,
    )
    valuation = engine.price(swap, snapshot)
    print(
        f"10Y payer 4.00%: NPV {valuation.npv:,.0f}, par rate {valuation.par_rate:.4%}, "
        f"annuity {valuation.annuity:,.0f}"
    )
    print(
        f"Legs: fixed PV {valuation.fixed_leg_pv:,.0f}, "
        f"floating PV {valuation.floating_leg_pv:,.0f}"
    )

    dv01 = parallel_dv01(lambda m: engine.price(swap, m).npv, snapshot, CURVE)
    print(f"Curve DV01 {dv01:,.0f} (negative: a payer gains when rates rise)")


if __name__ == "__main__":
    main()
