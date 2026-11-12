# Getting started

## Requirements

- Python 3.12 (pinned in `.python-version`)
- [uv](https://docs.astral.sh/uv/) for environments and locking

## Install and run the checks

```bash
git clone https://github.com/Djewiet/pricing-risk-engine.git
cd pricing-risk-engine
uv sync                      # dev + validation groups (QuantLib included)

uv run pytest --cov          # unit tests, coverage gate at 90%
uv run pytest validation     # QuantLib benchmark suite
uv run mypy                  # mypy --strict on src, tests, validation, examples
uv run ruff check . && uv run ruff format --check .
```

The documentation site is built with MkDocs Material, from its own dependency group:

```bash
uv run --group docs mkdocs serve           # live preview on http://127.0.0.1:8000
uv run --group docs mkdocs build --strict  # what CI runs
```

## Price a first bond

[`examples/price_bond.py`](https://github.com/Djewiet/pricing-risk-engine/blob/main/examples/price_bond.py)
runs the whole chain offline on a fixed set of par yields: bootstrap, snapshot, pricing,
yield analytics, curve risk. It is executed by the test suite, so it cannot go stale.

```bash
uv run python examples/price_bond.py
```

```text
Curve: 11 pillars, max repricing error 8.7e-16
Bond 4.25% Aug-2035: clean 100.8052, accrued 1.5938, dirty 102.3989
YTM 4.1472%, modified duration 7.7232, convexity 71.74, yield DV01 0.0791
Curve DV01 0.0805, z-spread at 1 point below the curve price 0.12%
```

How to read these numbers:

- **Repricing error 8.7e-16**: the curve gives back every input par yield to machine
  precision. This is the first sanity check of a bootstrap.
- **Accrued 1.5938**: 138 days of a 184-day half-year coupon of 2.125, since 15 August.
- **Dirty = clean + accrued**: the buyer pays the dirty price; the market quotes the clean.
- **Yield DV01 0.0791 vs curve DV01 0.0805**: both are "the value of one basis point", but
  on different risk factors (the bond's own semi-annual yield vs the continuous zero rates of
  the whole curve). See [Bond analytics](finance/bond-analytics.md#yield-dv01-vs-curve-dv01).

## Price a swap

```bash
uv run python examples/price_swap.py
```

```text
10Y payer 4.00%: NPV 126,537, par rate 4.1536%, annuity 82,376,166
Legs: fixed PV 3,295,047, floating PV 3,421,584
Curve DV01 -8,279 (negative: a payer gains when rates rise)
```

The same `parallel_dv01` function computes the bond and the swap DV01: risk is written
against the snapshot, not against an instrument. See
[Interest rate swap](finance/interest-rate-swap.md#worked-example).

## Use live Treasury data

```python
from pricer.market import bootstrap_par_yield_curve
from pricer.market.sources.us_treasury import fetch_par_yields

curves = fetch_par_yields(2025)  # {date: (ParYieldQuote, ...)}, one entry per business day
as_of = max(curves)
curve = bootstrap_par_yield_curve(as_of, curves[as_of])
```

`fetch_par_yields` downloads one calendar year of the US Treasury *Daily Par Yield Curve
Rates* CSV (public, no API key). Parsing is pure and tested offline; the download is a thin
wrapper. See [ADR 0001](adr/0001-yield-curve-bootstrap.md) for why this source was chosen.
