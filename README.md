# Pricing & Risk Engine

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

A production-grade Python pricing and risk library, with a distributed, real-time risk
service built on top of it.

> **Status: phase 1 (foundations).** Dates and day counts, immutable market snapshot,
> yield-curve bootstrap from public par yields, fixed-rate bonds (pricing, yield, durations,
> convexity, z-spread, curve DV01), all validated against QuantLib.

## Design principles

- **Instrument / Model / Engine separation.** Instruments hold contract terms, models hold
  dynamics and parameters, engines compute. Engines are injected (Strategy pattern).
- **One immutable market input.** Every pricing call takes a `MarketSnapshot`; there is no
  global state, so any price can be recomputed from a persisted snapshot.
- **Explicit conventions.** Day counts, schedules and compounding are always passed
  explicitly; nothing is rolled or adjusted behind the caller's back.
- **Independent validation.** Every formula is checked against a closed form, an arbitrage
  relation or QuantLib (`validation/`).

## Quickstart

```bash
uv sync
uv run pytest --cov          # unit tests, coverage gate at 90%
uv run pytest validation     # QuantLib benchmark suite
uv run mypy && uv run ruff check .
```

```python
from datetime import UTC, date, datetime

from pricer.market import MarketSnapshot, bootstrap_par_yield_curve
from pricer.market.sources.us_treasury import fetch_par_yields

curves = fetch_par_yields(2025)  # US Treasury par yield curves
as_of = max(curves)
curve = bootstrap_par_yield_curve(as_of, curves[as_of])

snapshot = MarketSnapshot(
    timestamp=datetime.now(UTC),
    valuation_date=as_of,
    curves={"USD-TSY": curve},
)
print(snapshot.curve("USD-TSY").zero_rate(date(as_of.year + 10, as_of.month, 1)))
```

```python
from pricer.analytics import yield_analytics, yield_to_maturity
from pricer.engines import DiscountingBondEngine
from pricer.instruments import FixedRateBond
from pricer.risk import parallel_dv01

bond = FixedRateBond(issue_date=date(2023, 8, 15), maturity=date(2033, 8, 15), coupon_rate=0.03875)
engine = DiscountingBondEngine(curve_name="USD-TSY")

valuation = engine.price(bond, snapshot)  # clean, dirty, accrued
ytm = yield_to_maturity(bond, valuation.clean_price, as_of)
risk = yield_analytics(bond, ytm, as_of)  # durations, convexity, DV01
curve_dv01 = parallel_dv01(lambda m: engine.price(bond, m).npv, snapshot, "USD-TSY")
```

## Layout

```
src/pricer/
  dates/        tenors, schedules, day-count conventions
  market/       yield curves, bootstrap, volatility, MarketSnapshot
    sources/    public market-data loaders (US Treasury)
  instruments/  contract terms and cash flows (FixedRateBond)
  engines/      pricing engines, injected per instrument (DiscountingBondEngine)
  analytics/    yield-based measures: YTM, durations, convexity, z-spread
  risk/         bump-and-revalue risk (parallel curve DV01)
tests/          unit tests (pytest, hypothesis)
validation/     model validation against QuantLib
docs/adr/       architecture decision records
```

## Market data

The yield curve is bootstrapped from the US Treasury *Daily Par Yield Curve Rates*
(public, daily, no API key). See [ADR 0001](docs/adr/0001-yield-curve-bootstrap.md) for
the conventions and their limits.

## License

MIT
