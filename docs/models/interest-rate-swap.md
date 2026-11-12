# Interest rate swap

Model note for `pricer.instruments.InterestRateSwap` and `pricer.engines.DiscountingSwapEngine`.

## Product

A vanilla swap exchanges, on a notional `N` that is never paid:

- a **fixed leg** paying `N * K * tau_i` at each fixed payment date `t_i`;
- a **floating leg** paying `N * (R_j + s) * tau_j`, where `R_j` is the overnight rate
  (SOFR for USD) compounded daily over the period and known only at its end, and `s` a spread.

A *payer* pays fixed and receives floating; a *receiver* does the opposite. Defaults follow
USD SOFR OIS conventions: annual payments, ACT/360 on both legs.

## Valuation

The engine takes **two curves** from the market snapshot:

| Role | Used for | Phase 1 | Production (USD, CSA in USD cash) |
|---|---|---|---|
| Forecast curve `F` | Expected overnight fixings | US Treasury | SOFR |
| Discount curve `D` | Present value of every cash flow | US Treasury | SOFR |

Expected compounded rate (the daily factors telescope under the forecast curve):

```
R_j = (F(s_j) / F(e_j) - 1) / tau_j
```

Leg values, annuity and par rate:

```
PV_float = sum_j N (R_j + s) tau_j D(e_j)
A        = sum_i N tau_i D(t_i)             (fixed-leg PV per unit of rate)
PV_fixed = K * A
NPV      = sign * (PV_float - PV_fixed)     (sign = +1 payer, -1 receiver)
K*       = PV_float / A                     (par swap rate)
```

With a single curve (`F = D`) the floating leg collapses to `N (D(t_0) - D(T))`, so
`K* = (D(t_0) - D(T)) / sum_i tau_i D(t_i)`: the par swap rate is a par yield.

## Why the Treasury curve in phase 1

- Free, official data is available for Treasuries, not for SOFR swap rates (Bloomberg, ICE,
  CME licences).
- The engine never assumes `F = D`: switching to a SOFR curve, or to a term index projected
  on its own curve and discounted on OIS, only changes curve names in the engine.
- Consequence: swap rates are internally consistent but differ from market SOFR swap rates
  by the swap spread (negative at the long end, tens of basis points).

## Validation

- Closed forms: single-curve telescoping, par-rate formula, swap at par rate worth zero,
  payer = -receiver, flat-curve forward rate, spread shifts the par rate one for one.
- QuantLib `OvernightIndexedSwap` (daily compounding, null calendar), 6 swaps (spot,
  forward-starting, short stub at month end, 30/360 semi-annual vs quarterly, receiver,
  spread) x single- and two-curve: NPV and leg PVs within 1e-8 of notional, par rate
  within 1e-12.

## Limitations

- No past fixings: a swap whose floating coupon is already accruing is rejected.
- Unadjusted dates and no payment lag (real SOFR swaps pay two business days later).
- No convexity or timing adjustment: exact for an overnight index projected on its own
  curve, an approximation for other indices.
