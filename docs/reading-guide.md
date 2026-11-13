# Reading guide

This page tells you which files to read, in which order, and what to look for in each.
There are two routes: a **30-minute tour** that follows one pricing call from the top, and a
**complete reading** that goes bottom-up through the layers, the way the code depends on
itself.

Source links point to `main` on GitHub. Line counts are approximate and include docstrings,
which carry most of the financial explanations.

## Route 1: the 30-minute tour (top-down)

Follow one bond pricing from market quotes to risk numbers.

| # | File | Why read it | Look for |
|---|---|---|---|
| 1 | [`examples/price_bond.py`][example] (90 lines), then [`examples/price_swap.py`][example-swap] | The whole chain in five numbered steps. | The order of the steps: market data, snapshot, instrument + engine, analytics, risk. The swap script repeats it with another instrument and engine. |
| 2 | [`market/snapshot.py`][snapshot] (120) | The single market input of every pricing call. | `__post_init__` (validation, defensive copies), `with_curve` (bumps build new snapshots). |
| 3 | [`instruments/bond.py`][bond] (120) | What an instrument is, and is not. | No `price` method. Cash flows and accrued interest only, because they are contractual. |
| 4 | [`engines/base.py`][engine-base] then [`engines/bond.py`][engine-bond] (20 + 70) | Where the pricing happens. | The `PricingEngine` protocol, then `discount_bond`: one vectorised dot product. |
| 5 | [`risk/curve.py`][risk] (35) | How risk is computed without touching the engine. | `parallel_dv01` takes *any* `MarketSnapshot -> float` function. |

After this tour you can explain the architecture: who holds what, and why the price is a
pure function of (instrument, engine, snapshot).

## Route 2: the complete reading (bottom-up)

Each layer only depends on the layers above it in this list
(see [Architecture](architecture/index.md)).

### Step 0: context (15 min)

1. [`README.md`][readme]: scope and status.
2. [ADR 0001](adr/0001-yield-curve-bootstrap.md): the curve decisions (source,
   instruments, interpolation, solver) and their consequences. Most design questions on the
   curve are answered here.
3. [`errors.py`][errors] (20 lines): the exception hierarchy. Every deliberate error derives
   from `PricerError`, so the future risk service can tell a library failure (bad market
   data, failed bootstrap) from a bug.

### Step 1: dates (`pricer.dates`, 30 min)

Finance background: [Rates and day counts](finance/rates.md).

| File | Why | Look for |
|---|---|---|
| [`tenor.py`][tenor] | Calendar arithmetic is where bond libraries break first. | `add_months` clamps to month end without end-of-month rolling; `Tenor.advance(times=n)` shifts in one step to avoid day drift. |
| [`schedule.py`][schedule] | Coupon dates for bonds (and swaps). | Backward generation from maturity, short front stub, and the `first_is_regular` test: a bug found by the QuantLib benchmark (see [Validation](validation.md#what-the-benchmark-found)). |
| [`daycount.py`][daycount] | Turning a period into a year fraction. | The `DayCount` protocol; `ActualActualICMA` needs the reference period, which is why `Period` carries `ref_start` / `ref_end`. |

Tests to read alongside: `tests/dates/test_schedule.py` (stub and month-end cases).

### Step 2: curves (`pricer.market`, 1 h)

Finance background: [Yield curve bootstrap](finance/yield-curve.md).

| File | Why | Look for |
|---|---|---|
| [`curves.py`][curves] | The core abstraction: a curve *is* its discount function. | `YieldCurve` (ABC): subclasses implement only `discount_factors`, everything else is derived. `DiscountCurve.discount_factors`: log-linear interpolation is `np.interp` on `ln P`, plus flat-forward extrapolation. `ZeroSpreadedCurve`: a decorator, not a copy. |
| [`bootstrap.py`][bootstrap] | Building the curve from market quotes. | Module docstring (the par equation), `_ParBond` (cash-flow skeleton), `_solve_pillar` (Brent on the pillar zero rate). Why one pass is exact. |
| [`volatility.py`][volatility] | Placeholder for options (phase 2). | A `Protocol` from day one, so engines never depend on `FlatVolatility`. |
| [`snapshot.py`][snapshot] | Market state as a value. | Every curve must be anchored on the valuation date; timestamp must be tz-aware. |
| [`sources/us_treasury.py`][treasury] | Real data. | Pure parser + thin network wrapper (testable offline). Known approximation on bills. |

Tests: `tests/market/test_bootstrap.py` (round-trip and flat-curve closed form),
`tests/market/test_curves.py` (property-based tests with hypothesis).

### Step 3: instruments (`pricer.instruments`, 30 min)

Finance background: [Fixed-rate bond](finance/fixed-rate-bond.md).

| File | Why | Look for |
|---|---|---|
| [`cashflows.py`][cashflows] | The output of an instrument. | `Cashflow` is a closed union of `FixedCoupon` and `Redemption`, so consumers can match on it. |
| [`bond.py`][bond] | Contract terms of a bullet bond. | Default day count (ACT/ACT ICMA at the bond frequency), `remaining_cashflows` (flows *on* the settlement date belong to the seller), `accrued_amount`. |

### Step 4: engines (`pricer.engines`, 20 min)

| File | Why | Look for |
|---|---|---|
| [`base.py`][engine-base] | The Strategy interface. | Generic `PricingEngine[InstrumentT, ResultT]` with PEP 695 syntax: the result type is engine-specific (`BondValuation` here). |
| [`bond.py`][engine-bond] | The discounting engine. | `discount_bond` is a free function, reused by the z-spread solver; the engine class only picks the curve in the snapshot. |

### Step 4b: the swap (30 min)

Finance background: [Interest rate swap](finance/interest-rate-swap.md). Read it as a
second instance of the same pattern: what had to be added, and what did not change.

| File | Why | Look for |
|---|---|---|
| [`instruments/swap.py`][swap] | Two legs on two schedules. | `SwapDirection.sign`; `floating_leg` yields `OvernightCoupon`s without amounts, since the rate is not known yet. |
| [`engines/swap.py`][engine-swap] | The two-curve engine. | Module docstring (telescoping of daily compounding), `discount_swap` vectorised per leg, the rejection of an already-accruing coupon. |
| [`validation/test_swap_quantlib.py`][val-swap] | Independent check of the telescoped formula. | QuantLib compounds day by day; agreement to 1e-8 of notional. |

### Step 4c: options (45 min)

Finance background: [European options and Black-Scholes](finance/black-scholes.md), then
[ADR 0002](adr/0002-option-model-binding.md) for the model / engine split. This is the
first place where the third leg of Instrument / Model / Engine appears.

| File | Why | Look for |
|---|---|---|
| [`instruments/option.py`][option] | The contracts. | `VanillaOption` holds the shared terms, `EuropeanOption` / `AmericanOption` only fix `early_exercise`; `OptionType.sign` (the $\omega$ of the formulas, one code path for calls and puts); `payoff` vectorised over terminal spots, ready for Monte Carlo. |
| [`models/black_scholes.py`][model-bs] | What a model is when its parameters are market data. | Module docstring (the dynamics, why only $D_r(T)$ and $D_q(T)$ matter); `BlackScholesModel.inputs` resolves the snapshot once for every engine. |
| [`greeks/base.py`][greeks] | One result type for every way of computing Greeks. | Units: raw partial derivatives; theta convention (fixed zero rates to expiry). |
| [`engines/analytic_european.py`][engine-bs] | The closed form and its Greeks. | Black formula on the forward; `norm_cdf` through `erfc` (tail precision); the `stdev == 0` branch (expiry today, zero vol). |
| [`tests/engines/test_analytic_european.py`][test-bs] | How a formula is proven without QuantLib. | Parity, bounds, strike convexity and the Black-Scholes PDE under hypothesis; Greeks against snapshot bumps. |
| [`validation/test_european_option_quantlib.py`][val-bs] | The benchmark. | 162 cases incl. a bootstrapped curve between pillars; price and six Greeks to 1e-10. |
| [`greeks/bump.py`][bump] | Greeks for any engine. | Takes a `MarketSnapshot -> float` like `parallel_dv01`; the bump size trade-off (module docstring); theta by rolling the whole market. Background: [Greeks by bump and implied volatility](finance/option-risk.md). |
| [`market/curves.py`][curves] (`RolledCurve`), [`market/volatility.py`][volatility] (`ShiftedVolatility`) | The market scenarios behind theta and vega. | Two decorators, like `ZeroSpreadedCurve`: they wrap, they do not copy. `RolledCurve` keeps forwards. |
| [`engines/binomial.py`][tree] | A second engine for the same model, and the first for American options. Background: [American options and the binomial tree](finance/american-options.md). | `VanillaOption.early_exercise` read at each node instead of an `isinstance`; one vectorised operation per time step; Greeks from the first two steps; the `p` validity check. |
| [`engines/monte_carlo.py`][mc] | The third engine for the same model. Background: [Monte Carlo pricing](finance/monte-carlo.md). | Exact simulation of $S_T$; antithetic pairs and why the standard error uses pair averages; the control-variate regression; the engine holds a seed, not a generator (purity, common random numbers). |
| [`validation/test_monte_carlo_statistics.py`][val-mc] | How a random number is validated. | Coverage of the 95% interval over 400 seeds, mean and variance of the standardised errors. |
| [`analytics/option.py`][iv] | Implied volatility. | Bounds check before solving (existence and uniqueness), bracket doubling, why Brent rather than Newton. |

### Step 5: analytics and risk (45 min)

Finance background: [Bond analytics and risk](finance/bond-analytics.md).

| File | Why | Look for |
|---|---|---|
| [`analytics/bond.py`][analytics] | Yield-based measures, the trader's view of a bond. | Module docstring (all formulas), `yield_times` (street convention), closed-form derivatives in `yield_analytics`, Brent in `yield_to_maturity` and `z_spread`. |
| [`risk/curve.py`][risk] | Curve-based risk, the risk manager's view. | Central difference and its O(h²) error; sign convention (positive for a long position). |

### Step 6: how it is proven (45 min)

| File | Why | Look for |
|---|---|---|
| [`validation/test_yield_curve_quantlib.py`][val-curve] | The curve benchmark. | The QuantLib setup reproducing our conventions exactly (module docstring), the 5 shapes × 6 dates grid, the tolerance and its justification. |
| [`validation/test_bond_quantlib.py`][val-bond] | The bond benchmark. | Both libraries discount on the *same* curve, so the comparison isolates the bond code. |
| [`validation/report/`][report] | The generated Model Validation Report. | `benchmarks.py` reuses the test grids; `convergence.py` measures the order as a log-log slope; read the [report](validation-report/index.md) itself first. |
| [`pyproject.toml`][pyproject], [`.github/workflows/ci.yml`][ci] | The quality gates. | ruff rule set, `mypy --strict`, coverage gate, the separate validation job. |

## Where things will go

| Coming with | New files | Reading position |
|---|---|---|
| Business calendars, key-rate DV01 (phase 1) | `dates/calendar.py`, `risk/` | Step 1 and step 5. |
| Risk service (phase 4) | `src/service/` | Separate route, to be written. |

[readme]: https://github.com/Djewiet/pricing-risk-engine/blob/main/README.md
[example]: https://github.com/Djewiet/pricing-risk-engine/blob/main/examples/price_bond.py
[example-swap]: https://github.com/Djewiet/pricing-risk-engine/blob/main/examples/price_swap.py
[swap]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/instruments/swap.py
[engine-swap]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/engines/swap.py
[val-swap]: https://github.com/Djewiet/pricing-risk-engine/blob/main/validation/test_swap_quantlib.py
[option]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/instruments/option.py
[model-bs]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/models/black_scholes.py
[greeks]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/greeks/base.py
[engine-bs]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/engines/analytic_european.py
[test-bs]: https://github.com/Djewiet/pricing-risk-engine/blob/main/tests/engines/test_analytic_european.py
[val-bs]: https://github.com/Djewiet/pricing-risk-engine/blob/main/validation/test_european_option_quantlib.py
[bump]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/greeks/bump.py
[iv]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/analytics/option.py
[tree]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/engines/binomial.py
[mc]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/engines/monte_carlo.py
[val-mc]: https://github.com/Djewiet/pricing-risk-engine/blob/main/validation/test_monte_carlo_statistics.py
[errors]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/errors.py
[tenor]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/dates/tenor.py
[schedule]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/dates/schedule.py
[daycount]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/dates/daycount.py
[curves]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/market/curves.py
[bootstrap]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/market/bootstrap.py
[volatility]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/market/volatility.py
[snapshot]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/market/snapshot.py
[treasury]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/market/sources/us_treasury.py
[cashflows]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/instruments/cashflows.py
[bond]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/instruments/bond.py
[engine-base]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/engines/base.py
[engine-bond]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/engines/bond.py
[analytics]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/analytics/bond.py
[risk]: https://github.com/Djewiet/pricing-risk-engine/blob/main/src/pricer/risk/curve.py
[val-curve]: https://github.com/Djewiet/pricing-risk-engine/blob/main/validation/test_yield_curve_quantlib.py
[val-bond]: https://github.com/Djewiet/pricing-risk-engine/blob/main/validation/test_bond_quantlib.py
[pyproject]: https://github.com/Djewiet/pricing-risk-engine/blob/main/pyproject.toml
[ci]: https://github.com/Djewiet/pricing-risk-engine/blob/main/.github/workflows/ci.yml
[report]: https://github.com/Djewiet/pricing-risk-engine/tree/main/validation/report
