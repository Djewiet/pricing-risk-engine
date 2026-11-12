# Fixed-rate bond

## Product

A **fixed-rate bullet bond** pays a fixed coupon $c$ on its face amount $N$ at each coupon
date, and repays $N$ at maturity. US Treasury notes and bonds are the reference example:
semi-annual coupons, ACT/ACT ICMA.

Code: `pricer.instruments.FixedRateBond` (contract) and
`pricer.engines.DiscountingBondEngine` (pricing).

```python
from datetime import date

from pricer.instruments import FixedRateBond

bond = FixedRateBond(
    issue_date=date(2025, 8, 15),
    maturity=date(2035, 8, 15),
    coupon_rate=0.0425,  # 4.25%, decimal
    frequency=2,  # default: semi-annual
    face_amount=100.0,  # default
)  # day_count=None means ACT/ACT ICMA at the bond frequency
```

## Cash flows

The schedule is generated backward from maturity ([Rates](rates.md#tenors-and-schedules)).
For each period $[s_i, e_i]$ with reference period $[R_{i}^{s}, R_{i}^{e}]$:

$$
\text{coupon}_i = N \cdot c \cdot \tau(s_i, e_i), \qquad
\text{paid on } e_i,
$$

and the redemption $N$ is paid at maturity. Under ACT/ACT ICMA a regular period gives
$\tau = 1/f$, so a regular coupon is exactly $N c / f$.

These cash flows are **contractual**: they do not depend on any market. That is why they
live on the instrument (`bond.cashflows`), while the price lives in an engine.

## Price by discounting

On a discount curve $P$, the present value at settlement is

$$
\text{PV} = \sum_{t_k > t_{\text{settle}}} CF_k \, P(0, t_k).
$$

The sum runs over flows paid **strictly after** settlement: a coupon paid on the settlement
date belongs to the seller, who still holds the bond at the start of that day (QuantLib's
default, `includeSettlementDateFlows=False`).

In the engine this is one vectorised call:
`npv = amounts @ curve.discount_factors(times)`.

## Dirty price, clean price, accrued interest

Between two coupon dates the holder earns a growing share of the next coupon. When the bond
changes hands, the buyer will receive that coupon in full, so the buyer compensates the
seller for the part already earned, the **accrued interest**:

$$
AI = N \cdot c \cdot \tau(s, t_{\text{settle}}) \quad \text{(current period } [s, e] \text{)}.
$$

- **Dirty (full) price**: what is actually paid, $\text{PV}$ per 100 of face.
- **Clean price**: what is quoted, $\text{dirty} - AI$.

Quoting clean removes the saw-tooth pattern of the dirty price around coupon dates: a clean
price only moves with the market. `BondValuation` returns all three, per 100 of face, plus
the NPV in currency.

Worked example (from `examples/price_bond.py`): on 31-Dec-2025, the 4.25% Aug-2035 bond is
138 days into a 184-day period, so $AI = 2.125 \times 138 / 184 = 1.59375$. With a dirty
price of 102.3989, the clean price is 100.8052.

## Hypotheses and limits

- **Settlement T+0**: settlement is the curve reference date, i.e. the valuation date.
  Treasuries settle T+1; the difference is one day of carry.
- **One curve for all cash flows**, no credit or liquidity spread. The spread to the curve
  is measured separately by the [z-spread](bond-analytics.md#z-spread).
- **Unadjusted dates**, no ex-coupon period, no amortisation or call features.
- Short front stubs only (no long stubs).

## Validation

Against QuantLib `FixedRateBond` + `DiscountingBondEngine` on the same curve, 6 bonds
(seasoned, new, short stub, end-of-month, zero coupon, 30Y) × 3 valuation dates: clean,
dirty and accrued agree to $10^{-10}$. Unit tests cover the closed forms (each par bond of the
bootstrap prices at 100 on its own curve; a flat curve gives a geometric sum), the drop of
the dirty price by one coupon across a coupon date while the clean price stays continuous,
the settlement-date flow rule, and matured bonds.
