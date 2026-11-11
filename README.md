# Pricing & Risk Engine

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

A production-grade Python pricing and risk library, with a distributed, real-time risk
service built on top of it.

> **Status: phase 1 (foundations).** Dates and day counts, immutable market snapshot,
> yield-curve bootstrap from public par yields, validated against QuantLib.

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

## Layout

```
src/pricer/
  dates/        tenors, schedules, day-count conventions
  market/       yield curves, bootstrap, volatility, MarketSnapshot
    sources/    public market-data loaders (US Treasury)
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
