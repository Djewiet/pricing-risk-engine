"""End-to-end example: price a European option on an index with Black-Scholes.

Discounting uses the bootstrapped Treasury curve (same quotes as ``price_bond.py``), the
dividend yield is a flat curve, the volatility is flat. The analytic Greeks are printed in
market units, compared with bump-and-revalue Greeks, and a quoted price is inverted into an
implied volatility.

Run it with ``uv run python examples/price_option.py``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from pricer.analytics import implied_volatility
from pricer.dates import Tenor
from pricer.engines import AnalyticEuropeanEngine
from pricer.greeks import bump_greeks
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
    model = BlackScholesModel("USD-TSY", dividend_curve="SPX-DIV")
    engine = AnalyticEuropeanEngine(model)

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

    # Bump-and-revalue Greeks work with any engine: here they check the closed form.
    call = EuropeanOption("SPX", 6100.0, date(2026, 12, 18), OptionType.CALL)
    analytic = engine.price(call, snapshot).greeks
    bumped = bump_greeks(
        lambda m: engine.price(call, m).npv,
        snapshot,
        "SPX",
        "USD-TSY",
        dividend_curve="SPX-DIV",
    )
    for name in ("delta", "gamma", "vega", "rho"):
        exact, bump = getattr(analytic, name), getattr(bumped, name)
        print(f"call {name:>5}: analytic {exact:.6f}, bumped {bump:.6f}")
    print(
        f"call theta/day: analytic {analytic.theta_per_day:+.4f} (zero rates fixed), "
        f"one-day roll {bumped.theta_per_day:+.4f} (forwards realised)"
    )

    # Implied volatility: invert a quoted price (no volatility surface needed).
    quote = 450.0
    sigma = implied_volatility(call, quote, model, snapshot)
    print(f"call quoted {quote:.2f} -> implied volatility {sigma:.4%}")


if __name__ == "__main__":
    main()
