# Yield curve bootstrap

## What problem it solves

The market does not quote discount factors. It quotes instruments: here, the yields of
US Treasury notes and bonds issued at par. **Bootstrapping** finds the discount curve that
reprices every quoted instrument exactly. All pricing then goes through that curve.

Code: `pricer/market/bootstrap.py`. Decisions and alternatives:
[ADR 0001](../adr/0001-yield-curve-bootstrap.md).

## Input: par yields

The US Treasury publishes every business day the *Daily Par Yield Curve Rates*: for each
tenor (1M to 30Y), the coupon a bond issued today would need to trade at par. These are
read from a monotone-convex fit of recently auctioned securities, quoted on a semi-annual
bond-equivalent basis.

A **par yield** $c$ for maturity $T$ is the coupon that prices the bond at par. With coupon
dates $t_i$ and accrual fractions $\tau_i$ (ACT/ACT ICMA, so $\tau_i = 1/2$ on regular
periods), the bond price per unit of face is

$$
1 = c \sum_{i} \tau_i P(0, t_i) + P(0, T)
\quad\Longrightarrow\quad
c = \frac{1 - P(0, T)}{A(T)}, \qquad A(T) = \sum_i \tau_i P(0, t_i).
$$

$A(T)$ is the **annuity** (or PV01 of the coupon leg). The same formula gives the fair rate
of a swap; the swap will reuse it.

Conventions of the quoted bonds (`ParBondConvention`): semi-annual coupons, ACT/ACT ICMA,
unadjusted dates, backward schedule with a short front stub, settlement on the valuation
date (T+0).

## Algorithm

Quotes are sorted by maturity. Each quote adds one **pillar** at its maturity, whose
discount factor is the only unknown:

1. Pillars $1, \dots, k-1$ are already known.
2. For a trial zero rate $z$ at pillar $k$, build the curve with $P_k = e^{-z\, t_k}$.
3. Compute the implied par yield of bond $k$ on that trial curve.
4. Solve $\text{par\_yield}(z) - c_k = 0$ with **Brent's method** on
   $z \in [-50\%, 100\%]$, to $10^{-14}$.

Why solve, rather than read the answer off the formula? Coupons of bond $k$ that fall
*between* pillar $k-1$ and pillar $k$ are discounted by interpolation, so they depend on the
unknown $P_k$. The equation is non-linear in $P_k$.

Why is **one pass** enough? Because log-linear interpolation is *local*: pillar $k$ only
affects the curve between pillars $k-1$ and $k+1$, so solving pillar $k$ never changes the
price of bonds $1..k-1$. A global interpolator (cubic spline) would need a global iteration.

## Interpolation

Between pillars, $\ln P$ is linear in $t$ (`DiscountCurve`):

$$
\ln P(t) = \ln P(t_{j}) + \frac{t - t_j}{t_{j+1} - t_j}\big(\ln P(t_{j+1}) - \ln P(t_j)\big),
\qquad t_j \le t \le t_{j+1}.
$$

Equivalently, the instantaneous forward $f(t)$ is **constant on each segment**
("piecewise flat forwards"). Beyond the last pillar the last forward is extended
(flat-forward extrapolation). Times are ACT/365F year fractions from the reference date.

| Property | Log-linear on DF | Cubic spline on zero rates |
|---|---|---|
| Positive discount factors | Always | Not guaranteed |
| Locality (bump one pillar, move two segments) | Yes | No: a 30Y bump moves the 1Y forward |
| Sequential exact bootstrap | Yes | Needs global iteration |
| Smooth forwards | No: jumps at pillars | Yes, but can oscillate |

Smoothness matters for products that depend on the forward curve shape (caps, CMS); for
discounting and vanilla swaps, locality and robustness matter more. Monotone-convex
(Hagan–West) combines both and is the candidate for v2.

## Worked check: flat par yields

If every par yield equals $c$ and every coupon date is a pillar (tenors on a 6M grid), each
bond is a regular semi-annual bond and the bootstrap has a closed form:

$$
P(0, n \times 6\text{M}) = \left(1 + \tfrac{c}{2}\right)^{-n}.
$$

`tests/market/test_bootstrap.py` checks this, plus the round trip: `par_yield(curve, T)`
gives back every input quote (to $10^{-12}$; the example script shows $8.7 \times 10^{-16}$).

## Hypotheses and limits

- **Bills treated as par bonds.** Quotes up to 1Y come from T-bills (zero-coupon, BEY
  convention), treated here as semi-annual par yields. The error is a fraction of a basis
  point at the short end.
- **No calendar**: unadjusted dates (see [Rates](rates.md#limits-phase-1)).
- **A sovereign curve.** Treasury yields embed a convenience yield and are not the
  discounting curve of collateralised derivatives (SOFR OIS). Using it for swaps is a
  phase 1 simplification, discussed on the [swap page](interest-rate-swap.md).
- **Forwards jump at pillars**, by construction.

## Validation

Discount factors match QuantLib's `PiecewiseLogLinearDiscount` built from
`FixedRateBondHelper`s with identical conventions to $10^{-11}$ (QuantLib's own solver
accuracy is $10^{-12}$), on 5 curve shapes (normal, inverted, humped, negative, flat) ×
6 reference dates chosen to stress month-end date generation. See [Validation](../validation.md).
