"""End-to-end example: price a European option on an index with Black-Scholes.

Discounting uses the bootstrapped Treasury curve (same quotes as ``price_bond.py``), the
dividend yield is a flat curve, the volatility is flat. The analytic Greeks are printed in
market units next to their raw values, then checked by bumping the snapshot.

Run it with ``uv run python examples/price_option.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pricer.dates import Tenor
from pricer.engines import AnalyticEuropeanEngine
from pricer.instruments import EuropeanOption, OptionType
from pricer.market import (
    FlatForwardCurve,
    FlatVolatility,
    MarketSnapshot,
    ParYieldQuote,
    bootstrap_par_yield_curve,
)
from pricer.models import BlackScholesModel

VALUATION_DATE = date(2025, 12, 31)

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
        curves={
            "USD-TSY": bootstrap_par_yield_curve(VALUATION_DATE, quotes),
            "SPX-DIV": FlatForwardCurve(VALUATION_DATE, 0.013),
        },
        spots={"SPX": 6000.0},
        volatilities={"SPX": FlatVolatility(0.18)},
    )
    engine = AnalyticEuropeanEngine(BlackScholesModel("USD-TSY", dividend_curve="SPX-DIV"))

    # One-year 6100 call and put on the index.
    for option_type in OptionType:
        option = EuropeanOption("SPX", 6100.0, date(2026, 12, 18), option_type)
        value = engine.price(option, snapshot)
        g = value.greeks
        print(
            f"{option_type.value:>4} 6100 Dec-26: {value.npv:8.2f}  forward {value.forward:.2f}  "
            f"delta {g.delta:+.4f}  gamma {g.gamma:.6f}  vega/1% {g.vega / 100:.2f}  "
            f"theta/day {g.theta_per_day:+.3f}  rho/1bp {g.rho / 1e4:+.4f}"
        )

    # The analytic delta is what the risk service will get by bumping the spot.
    call = EuropeanOption("SPX", 6100.0, date(2026, 12, 18), OptionType.CALL)
    up = engine.price(call, snapshot.with_spot("SPX", 6001.0)).npv
    down = engine.price(call, snapshot.with_spot("SPX", 5999.0)).npv
    print(
        f"call delta: analytic {engine.price(call, snapshot).greeks.delta:.6f}, "
        f"bumped {(up - down) / 2.0:.6f}"
    )


if __name__ == "__main__":
    main()
