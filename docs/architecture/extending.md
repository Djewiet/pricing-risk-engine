# Extending the library

The architecture is designed so that a new product or method is *added*, not patched in.
This page is the checklist, illustrated with the interest rate swap.

## Adding an instrument

1. **Contract terms** in `src/pricer/instruments/<product>.py`: a frozen dataclass that
   validates its inputs in `__post_init__` and exposes its contractual cash flows. It must
   not import from `engines/` or read market data.
2. **Cash flow types** in `instruments/cashflows.py` if the existing ones do not fit (a
   floating coupon needs a fixing period and an index, not an amount), and add them to the
   `Cashflow` union.
3. **Engine** in `src/pricer/engines/<product>.py`: a frozen dataclass implementing
   `PricingEngine[Instrument, Result]`, with the names of the market data it needs as
   attributes (e.g. `curve_name`). Keep the computation in a free function taking curves,
   so that solvers (z-spread, fair rate) can call it without building snapshots.
4. **Result type**: a frozen dataclass next to the engine, with documented units.
5. **Exports** in the package `__init__.py` and `__all__`.
6. **Tests** in `tests/` mirroring `src/`:
    - a closed form (e.g. a par instrument prices at par on its own curve);
    - at least one arbitrage or sanity property (e.g. payer + receiver = 0);
    - edge cases: expired instrument, settlement on a payment date, stub periods.
7. **QuantLib benchmark** in `validation/test_<product>_quantlib.py`, reproducing the same
   conventions (NullCalendar, Unadjusted, zero settlement days) and with a tolerance
   justified in a comment.
8. **Documentation**: a page in `docs/finance/`, a row in the
   [reading guide](../reading-guide.md), and the class in the
   [class model](class-model.md).

## Adding a pricing method

A new method for an existing instrument (a spread engine, a tree, a Monte Carlo) is a new
engine class. The instrument and the existing engines do not change. If you are tempted to
write `if isinstance(instrument, ...)` inside an engine, you need a second engine.

## Adding a risk measure

Write it against the `MarketSnapshot -> float` signature, like `parallel_dv01`. It then
applies to every instrument and to a portfolio sum without modification. Build bumped
markets with `MarketSnapshot.with_curve` / `with_spot` / `with_volatility`.

## Adding a curve type

Subclass `YieldCurve` and implement `discount_factors(times)` vectorised over a NumPy array.
Everything else (`discount`, `zero_rate`, `forward_rate`, the use by every engine) follows.
Add a QuantLib benchmark on the equivalent QuantLib curve.

## Worked example: the swap

The swap followed this checklist exactly:

| Step | File | Content |
|---|---|---|
| Contract terms | `instruments/swap.py` | `InterestRateSwap`, `SwapDirection`; both legs generated on `Schedule`. |
| Cash flow type | `instruments/cashflows.py` | `OvernightCoupon`: no amount, since the rate is unknown until the period ends; it carries the accrual period and the spread. |
| Engine | `engines/swap.py` | `DiscountingSwapEngine(discount_curve, forecast_curve)` and the pure function `discount_swap(swap, discount, forecast)`. |
| Result | `engines/swap.py` | `SwapValuation`: NPV, leg PVs, annuity, par rate. |
| Unit tests | `tests/instruments/test_swap.py`, `tests/engines/test_swap_engine.py` | Telescoping, par rate closed form, payer = −receiver, two-curve roles. |
| Benchmark | `validation/test_swap_quantlib.py` | QuantLib `OvernightIndexedSwap`, single- and two-curve. |
| Docs | `finance/interest-rate-swap.md` | Product, formulas, curve choice, limits. |

No existing engine or instrument was modified; `pricer.risk.parallel_dv01` gives the swap
DV01 for free.
