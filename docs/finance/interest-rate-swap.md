# Interest rate swap

## Product

A vanilla interest rate swap exchanges, on a notional $N$ that is never paid:

- a **fixed leg** paying $N K \tau_i$ at each fixed payment date $t_i$;
- a **floating leg** paying $N (R_j + s)\tau_j$ at each floating payment date $e_j$, where
  $R_j$ is the overnight rate (SOFR for USD) compounded daily over the period
  $[s_j, e_j]$, known only at its end, and $s$ a spread.

A **payer** pays fixed and receives floating: it gains when rates rise. A **receiver**
does the opposite. The side is named after the fixed leg (`SwapDirection.PAYER` /
`RECEIVER`, with `.sign` equal to $+1$ / $-1$).

Defaults follow USD SOFR OIS conventions: annual payments and ACT/360 on both legs,
unadjusted dates, backward schedules with a short front stub, no payment lag.

Code: `pricer.instruments.InterestRateSwap` (contract, both legs as cash flows),
`pricer.instruments.OvernightCoupon` (floating cash flow),
`pricer.engines.DiscountingSwapEngine` and the pure function `discount_swap`, result
`pricer.engines.SwapValuation`.

```python
from datetime import date

from pricer.engines import DiscountingSwapEngine
from pricer.instruments import InterestRateSwap, SwapDirection

swap = InterestRateSwap(
    effective_date=date(2025, 12, 31),
    maturity=date(2035, 12, 31),
    fixed_rate=0.04,
    notional=10_000_000.0,
    direction=SwapDirection.PAYER,
)
engine = DiscountingSwapEngine(discount_curve="USD-TSY", forecast_curve="USD-TSY")
```

## Two curves, two roles

The engine reads **two curves** from the snapshot, by name:

| Role | Used for | Phase 1 | Production (USD, CSA in USD cash) |
|---|---|---|---|
| Forecast curve $F$ | Expected overnight fixings | US Treasury | SOFR |
| Discount curve $D$ | Present value of every cash flow | US Treasury | SOFR |

Since 2008, the market no longer assumes one curve does both jobs: the index being
projected (SOFR, Euribor 3M...) and the collateral rate that discounts (the CSA rate,
usually the OIS) can differ. The engine never assumes $F = D$, so switching to a SOFR
curve, or projecting a term index on its own curve while discounting on OIS, only changes
curve names.

## Valuation

**Floating leg.** A coupon that compounds the overnight rate $r_d$ from $s_j$ to $e_j$ pays
$\prod_d (1 + r_d \delta_d) - 1$ per unit of notional. Under the forecast curve, each daily
growth factor is expected to be $F(t_d)/F(t_{d+1})$, so the product **telescopes**:

$$
R_j = \frac{1}{\tau_j}\left(\frac{F(s_j)}{F(e_j)} - 1\right).
$$

No day-by-day loop is needed, and no convexity adjustment when the forecast curve is the
curve of the overnight index itself.

**Leg values, annuity, par rate.**

$$
\begin{aligned}
PV_{\text{float}} &= \sum_j N (R_j + s)\, \tau_j\, D(e_j) \\
A &= \sum_i N \tau_i\, D(t_i) \qquad \text{(annuity: fixed-leg PV per unit of rate)} \\
PV_{\text{fixed}} &= K A \\
\text{NPV} &= \text{sign} \times (PV_{\text{float}} - PV_{\text{fixed}}) \\
K^* &= PV_{\text{float}} / A \qquad \text{(par swap rate)}
\end{aligned}
$$

Hence $\text{NPV} = \text{sign} \times (K^* - K) \times A$: a swap is worth the difference
between the market rate and its own rate, times the annuity. One basis point of fixed rate
is worth $A \times 10^{-4}$, the **PV01**.

**Single curve.** With $F = D$ and both legs starting at $t_0$, the floating leg collapses to
$N\,(D(t_0) - D(T))$ and

$$
K^* = \frac{D(t_0) - D(T)}{\sum_i \tau_i D(t_i)},
$$

which is the [par yield](yield-curve.md#input-par-yields) formula: on one curve, a par swap
rate is a par yield with the swap's own conventions.

## Worked example

`examples/price_swap.py`, 10Y payer at 4%, 10 million notional, Treasury curve of the
bond example for both roles:

```text
10Y payer 4.00%: NPV 126,537, par rate 4.1536%, annuity 82,376,166
Legs: fixed PV 3,295,047, floating PV 3,421,584
Curve DV01 -8,279 (negative: a payer gains when rates rise)
```

Check: $(4.1536\% - 4.00\%) \times 82.38\text{m} \approx 126.5\text{k}$. The PV01 is
$82.38\text{m} \times 10^{-4} \approx 8{,}238$, close to the curve DV01: moving the curve by
1 bp moves the par rate by about 1 bp. The small difference comes from the floating leg's
own sensitivity and from discounting.

## Why the Treasury curve in phase 1

- Free, official data exists for Treasuries, not for SOFR swap rates (licensed by
  Bloomberg, ICE, CME).
- The engine is two-curve from day one, so the data limitation does not leak into the code.
- Consequence: swap rates are internally consistent but differ from market SOFR swap rates
  by the **swap spread** (negative at the long end, tens of basis points).

## Hypotheses and limits

- **No past fixings.** A swap whose floating coupon is already accruing on the valuation
  date is rejected (`PricerError`) rather than priced with a guessed fixing. Supporting it
  needs a fixings history in the snapshot.
- **Unadjusted dates and no payment lag.** Real SOFR swaps pay two business days after the
  period end.
- **No convexity or timing adjustment**: exact for an overnight index projected on its own
  curve, an approximation for other indices.

## Validation

- **Closed forms and properties** (`tests/engines/test_swap_engine.py`): single-curve
  telescoping, single-curve par rate formula, swap at par rate worth zero,
  payer = −receiver, flat-curve forward rate, a spread shifts the par rate one for one,
  forecast and discount curves play distinct roles, forward-starting swaps, a payment on
  the valuation date is excluded, DV01 through the snapshot.
- **QuantLib** (`validation/test_swap_quantlib.py`): `OvernightIndexedSwap` with daily
  compounding on a `NullCalendar` index (QuantLib compounds the daily forwards one by one,
  which independently checks the telescoped formula). Six swaps (spot, 30Y receiver,
  forward-starting, short stub at month end, 30/360 semi-annual vs quarterly, spread) ×
  single- and two-curve: NPV and leg PVs within $10^{-8}$ of notional, par rate within
  $10^{-12}$.
