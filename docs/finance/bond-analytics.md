# Bond analytics and risk

Two families of measures, which answer different questions:

- **Yield-based** (`pricer.analytics`): the bond in isolation, through its own yield.
  This is how a bond is quoted and how a trader thinks about it.
- **Curve-based** (`pricer.risk`, z-spread): the bond against the market curve. This is
  what aggregates across a portfolio.

## Yield to maturity

The **yield to maturity** $y$ is the single rate that, used to discount every cash flow,
gives back the market dirty price. With the street convention (compounding at the coupon
frequency $f$):

$$
P_{\text{dirty}}(y) = \sum_k CF_k \left(1 + \frac{y}{f}\right)^{-f\, t_k},
$$

where $t_k$ are **yield-times**: accumulated period by period with the bond's day count, so
each regular ACT/ACT ICMA period counts exactly $1/f$ and the first, partial period counts
the unexpired fraction $w/f$. This gives the textbook form
$\sum_k CF_k (1 + y/f)^{-(k-1+w)}$.

$P(y)$ is strictly decreasing, so the root is unique; it is found with Brent's method
(`yield_to_maturity`, tolerance $10^{-14}$).

## Durations and convexity

Derivatives of the price with respect to the yield, in closed form
(`yield_analytics`):

| Measure | Formula | Meaning |
|---|---|---|
| Macaulay duration | $D = \dfrac{1}{P}\sum_k t_k\, CF_k\, (1+y/f)^{-f t_k}$ | PV-weighted average time of the cash flows (years) |
| Modified duration | $D_{\text{mod}} = -\dfrac{P'(y)}{P} = \dfrac{D}{1 + y/f}$ | Relative price change per unit of yield |
| Convexity | $C = \dfrac{P''(y)}{P} = \dfrac{1}{P}\sum_k CF_k\, t_k \left(t_k + \tfrac{1}{f}\right)(1+y/f)^{-f t_k - 2}$ | Curvature of the price-yield relation |
| Yield DV01 | $-P'(y) \times 10^{-4}$ | Price change (per 100) for a 1 bp fall in yield |

Second-order price change for a yield move $\Delta y$:

$$
\frac{\Delta P}{P} \approx -D_{\text{mod}}\, \Delta y + \frac{1}{2} C\, (\Delta y)^2.
$$

Convexity is positive for a bullet bond: the price rises more when yields fall than it
drops when yields rise by the same amount. Unit tests check the closed-form derivatives against finite
differences, that the second-order expansion beats the first-order one, and the
price-yield round trip (property-based, with hypothesis, over a range of yields).

## Curve DV01

The **curve DV01** is the value change when every continuously-compounded zero rate of the
curve falls by 1 bp. It is computed by bump-and-revalue (`pricer.risk.parallel_dv01`) with
a central difference:

$$
\text{DV01} = \frac{V(-h) - V(+h)}{2} \cdot \frac{1\,\text{bp}}{h}.
$$

The central scheme cancels the second-order (convexity) term, so the error is $O(h^2)$
instead of $O(h)$ for a one-sided bump. The shifted curves are `ZeroSpreadedCurve`s,
$P'(t) = P(t)\, e^{\mp h t}$, inserted into *new* snapshots: the base market is never
modified. The sign convention is positive for a long bond position.

`parallel_dv01` takes any function `MarketSnapshot -> float`, so the same code gives the
DV01 of a swap or of a portfolio.

### Yield DV01 vs curve DV01

On the example bond, the yield DV01 is 0.0791 and the curve DV01 is 0.0805. Neither is
wrong: they bump different risk factors.

- The yield DV01 moves the bond's own semi-annually compounded yield by 1 bp.
- The curve DV01 moves the continuous zero rates of the whole curve by 1 bp.

A 1 bp move in a continuous rate is a move of about $(1 + y/2)$ bp in a semi-annual rate, so
the two differ by roughly $y/2$ in relative terms (about 2% at 4%). The curve DV01 is the
one that **aggregates**: all positions on the same curve share the same risk factor, so
their DV01s add up. The yield DV01 is a per-bond quoting measure.

## Z-spread

The **z-spread** $s$ is the constant shift of the zero curve that reprices the bond at its
market price:

$$
P_{\text{market}} = \sum_k CF_k\, P(0, t_k)\, e^{-s\, t_k}.
$$

It measures what the bond pays above the reference curve (credit, liquidity, specialness)
across the whole term structure, rather than at a single yield. Solved with Brent's method
on `ZeroSpreadedCurve` (`z_spread`). On the curve's own price, the z-spread is 0.

## Hypotheses and limits

- Yield measures assume a flat yield curve and a parallel move of it; they ignore the
  shape of the curve.
- The parallel curve DV01 says nothing about curve-shape risk (steepening, flattening).
  **Key-rate DV01** (bump each par yield, re-bootstrap) is on the
  [roadmap](../roadmap.md).
- Bump size $h = 1$ bp. For a zero-coupon bond maturing at $t$ the central scheme is
  exact up to a relative error of order $(h t)^2$, about $10^{-6}$ at 10 years, which the
  unit tests assert; smaller bumps would start to lose digits to cancellation.

## Validation

Against QuantLib `BondFunctions` with `Compounded` at the bond frequency, same 18 cases as
the pricing: yield to $10^{-11}$, Macaulay and modified durations and convexity to
$10^{-9}$ relative, z-spread to $10^{-9}$.
