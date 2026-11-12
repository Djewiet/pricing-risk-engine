"""End-to-end example: bootstrap a curve, price a bond, compute its risk.

Runs offline on a fixed set of par yields (the US Treasury curve shape of late 2025), so
the output is reproducible. Swap ``QUOTES`` for :func:`fetch_par_yields` to use live data.

Run it with ``uv run python examples/price_bond.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pricer.analytics import yield_analytics, yield_to_maturity, z_spread
from pricer.dates import Tenor
from pricer.engines import DiscountingBondEngine
from pricer.instruments import FixedRateBond
from pricer.market import MarketSnapshot, ParYieldQuote, bootstrap_par_yield_curve, par_yield
from pricer.risk import parallel_dv01

VALUATION_DATE = date(2025, 12, 31)
CURVE = "USD-TSY"

#: Par yields in percent, by tenor.
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
    # 1. Market data: bootstrap a discount curve from par yields.
    quotes = [ParYieldQuote(Tenor.parse(t), r / 100.0) for t, r in QUOTES.items()]
    curve = bootstrap_par_yield_curve(VALUATION_DATE, quotes)
    worst = max(abs(par_yield(curve, q.tenor.advance(VALUATION_DATE)) - q.rate) for q in quotes)
    print(f"Curve: {len(curve.pillar_dates)} pillars, max repricing error {worst:.1e}")

    # 2. The snapshot is the single, immutable market input of every pricing call.
    snapshot = MarketSnapshot(
        timestamp=datetime(2025, 12, 31, 21, 0, tzinfo=UTC),
        valuation_date=VALUATION_DATE,
        curves={CURVE: curve},
    )

    # 3. Instrument (contract terms only) and engine (the pricing method), kept apart.
    bond = FixedRateBond(
        issue_date=date(2025, 8, 15), maturity=date(2035, 8, 15), coupon_rate=0.0425
    )
    engine = DiscountingBondEngine(curve_name=CURVE)
    valuation = engine.price(bond, snapshot)
    print(
        f"Bond 4.25% Aug-2035: clean {valuation.clean_price:.4f}, "
        f"accrued {valuation.accrued_interest:.4f}, dirty {valuation.dirty_price:.4f}"
    )

    # 4. Yield-based analytics, from the price.
    ytm = yield_to_maturity(bond, valuation.clean_price, VALUATION_DATE)
    analytics = yield_analytics(bond, ytm, VALUATION_DATE)
    print(
        f"YTM {ytm:.4%}, modified duration {analytics.modified_duration:.4f}, "
        f"convexity {analytics.convexity:.2f}, yield DV01 {analytics.dv01:.4f}"
    )

    # 5. Curve-based risk, by bump-and-revalue on the snapshot.
    dv01 = parallel_dv01(lambda m: engine.price(bond, m).npv, snapshot, CURVE)
    spread = z_spread(bond, valuation.clean_price - 1.0, curve)
    print(f"Curve DV01 {dv01:.4f}, z-spread at 1 point below the curve price {spread:.2%}")


if __name__ == "__main__":
    main()
