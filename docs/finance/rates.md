# Rates and day counts

This page sets the vocabulary used everywhere else: discount factors, the ways a rate can
be quoted, and how calendar dates become year fractions.

## Discount factor

The **discount factor** $P(0, t)$ is the price today of one unit of currency paid at time
$t$. It is the primitive of every rates library: a yield curve *is* the function
$t \mapsto P(0, t)$, and every rate is a way of re-expressing it.

Under no-arbitrage, with positive rates, $P$ is decreasing from $P(0,0)=1$. With negative
rates (EUR, CHF, JPY 2015–2022) $P$ can exceed 1; the library allows it.

Code: `YieldCurve.discount_factors(times)` (vectorised) and `YieldCurve.discount(d)`.

## Compounding

The same discount factor can be quoted as a rate in several ways
(`pricer.market.curves.Compounding`):

| Compounding | Definition | Typical use |
|---|---|---|
| Continuous | $P = e^{-r t}$ | Curve internals, z-spread, model maths |
| Simple | $P = \dfrac{1}{1 + r t}$ | Money-market deposits, Libor/SOFR-style fixings |
| Compounded $m$ times a year | $P = (1 + r/m)^{-m t}$ | Bond yields ($m = 2$ for US Treasuries) |

A rate without its compounding and day count is not a number you can use. 4% continuous
is 4.0405% compounded semi-annually.

Code: `rate_from_discount` and `discount_from_rate`, tested to be exact inverses by
property-based tests (hypothesis).

## Zero rate and forward rates

The **zero rate** to $t$ (continuous) is $z(t) = -\ln P(0,t) / t$: the constant rate that
gives the same discount factor.

The **forward rate** between $t_1$ and $t_2$ is the rate you can lock in today for that
future period. No-arbitrage forces it: investing to $t_2$ must yield the same as investing
to $t_1$ then rolling at the forward, so the forward discount factor is

$$
P(t_1, t_2) = \frac{P(0, t_2)}{P(0, t_1)}, \qquad
F_{\text{simple}}(t_1, t_2) = \frac{1}{t_2 - t_1}\left(\frac{P(0,t_1)}{P(0,t_2)} - 1\right).
$$

The **instantaneous forward** is $f(t) = -\dfrac{\partial \ln P(0,t)}{\partial t}$. The
interpolation choice on the curve is a choice about the shape of $f$: see
[Yield curve](yield-curve.md#interpolation).

Code: `YieldCurve.zero_rate`, `YieldCurve.forward_rate`.

## Day counts

A **day count** turns a period $[d_1, d_2]$ into a year fraction $\tau$. It is part of the
contract: the same coupon rate pays different amounts under different conventions.

| Convention | Year fraction | Used for | Class |
|---|---|---|---|
| ACT/360 | $\dfrac{d_2 - d_1}{360}$ | USD/EUR money market, SOFR and €STR legs | `Actual360` |
| ACT/365F | $\dfrac{d_2 - d_1}{365}$ | GBP markets; **the curve time axis here** | `Actual365Fixed` |
| 30/360 Bond Basis | $\dfrac{360\Delta Y + 30 \Delta M + \Delta D}{360}$ with day-31 rules | USD corporate bonds, swap fixed legs | `Thirty360BondBasis` |
| ACT/ACT ISDA | days in leap years / 366 + days in other years / 365 | Some swap legs | `ActualActualISDA` |
| ACT/ACT ICMA | $\dfrac{d_2 - d_1}{f \cdot (R_2 - R_1)}$, with $[R_1, R_2]$ the reference coupon period | US Treasuries, most government bonds | `ActualActualICMA` |

ACT/ACT ICMA is the important one for bonds: a **regular** coupon period accrues exactly
$1/f$, whatever its length in days (181 or 184 days for a half-year). That is why a 4.25%
semi-annual Treasury pays exactly 2.125 per 100 every six months. Computing it needs the
reference period, which is why `Period` carries `ref_start` and `ref_end`.

!!! warning "Two different time axes"
    Instruments accrue with their contractual day count. The curve measures time with its
    own convention (ACT/365F by default) to look up discount factors. Mixing the two is a
    classic source of basis-point errors. Here they are separate by design:
    `bond.accrual_day_count` vs `curve.day_count`.

## Tenors and schedules

A **tenor** (`Tenor`) is a length in calendar units: `6M`, `10Y`, `6W`. Month arithmetic
clamps to the end of the month (`31-Jan + 1M = 28-Feb`) without end-of-month rolling, like
QuantLib with `endOfMonth=False`.

A **schedule** (`Schedule`) is the list of coupon dates. It is generated **backward from
maturity**, the market standard for bonds and swaps: coupon dates are anchored on the
maturity, and if the life is not a whole number of periods the irregular period is a
**short front stub**.

```text
issue 10-Jan-2024                          maturity 15-Jun-2031
   |-- stub --|-------- 6M --------|-- ... --|-------- 6M --------|
 10-Jan-24  15-Jun-24          15-Dec-24          15-Dec-30    15-Jun-31
   reference period of the stub: [15-Dec-23, 15-Jun-24]
```

The stub accrues $\tau = \dfrac{\text{days}(10\text{-Jan}, 15\text{-Jun})}{2 \times \text{days}(15\text{-Dec}, 15\text{-Jun})}$ under ACT/ACT ICMA.

## Limits (phase 1)

- **No business-day calendar.** Dates are unadjusted: a coupon falling on a Saturday is
  paid on Saturday. Real Treasury and swap flows roll to the next business day. A US
  government bond calendar is on the [roadmap](../roadmap.md).
- **No long stubs** in ACT/ACT ICMA (they need several reference periods).
- **No payment lag**: coupons are paid on their accrual end date.
