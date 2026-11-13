# European options and Black-Scholes

## Product

A **European call** (put) gives the right, not the obligation, to buy (sell) one unit of an
underlying at the strike $K$ on the expiry date $T$, and only on that date. With
$\omega = +1$ for a call and $-1$ for a put, the payoff at expiry is

$$
\text{payoff} = \max\big(\omega (S_T - K), 0\big).
$$

Code: `pricer.instruments.EuropeanOption` (underlying identifier, strike, expiry, type) and
`pricer.instruments.OptionType` (`CALL` / `PUT`, with `.sign` $= \omega$). As for bonds and
swaps, the instrument has no `price` method: it knows its payoff, which is contractual, not
its value, which depends on a model.

## The model

Black-Scholes-Merton assumes that, under the risk-neutral measure, the spot follows a
geometric Brownian motion

$$
\frac{dS_t}{S_t} = (r_t - q_t)\,dt + \sigma\,dW_t
$$

with $r$ the risk-free rate, $q$ the continuous dividend yield (or repo / borrow cost) and
$\sigma$ the volatility, all deterministic. Only two numbers from the curves matter for a
European option: the discount factors to expiry

$$
D_r = e^{-\int_0^T r_t\,dt}, \qquad D_q = e^{-\int_0^T q_t\,dt},
$$

which give the **forward** $F = S_0 D_q / D_r$, the price agreed today for delivery at $T$
at zero cost. $\ln S_T$ is then normal with mean $\ln F - \sigma^2 T/2$ and variance
$\sigma^2 T$: the drift $-\sigma^2 T / 2$ makes $E[S_T] = F$ exactly.

Code: `pricer.models.BlackScholesModel(discount_curve, dividend_curve=None)`. The model holds
no market data: it says which curves of the snapshot play the roles of $r$ and $q$, and its
`inputs(...)` method resolves, for one option, the spot, $T$, $D_r$, $D_q$ and $\sigma(T, K)$
(`BlackScholesInputs`). Why this split is described in
[ADR 0002](../adr/0002-option-model-binding.md).

**Time.** $T$ is measured in ACT/365F from the valuation date to expiry, the equity-option
convention. The curves keep their own time axis for discounting; with the default ACT/365F
curves the two coincide.

## The formula

Pricing by replication (or, equivalently, as a discounted risk-neutral expectation) gives,
written on the forward (Black 1976):

$$
V = \omega\,\big(S D_q\,N(\omega d_1) - K D_r\,N(\omega d_2)\big),
\qquad
d_{1,2} = \frac{\ln(F/K) \pm \tfrac12 \sigma^2 T}{\sigma\sqrt{T}}.
$$

How to read it, for a call:

- $N(d_2)$ is the risk-neutral probability of finishing in the money, so $K D_r N(d_2)$ is the
  present value of paying the strike in that event;
- $D_q N(d_1)$ is the **delta**: the number of shares held in the replicating portfolio, and
  $S D_q N(d_1)$ the present value of receiving the share in that event (measured under the
  share measure, hence $d_1 \ne d_2$).

Code: `pricer.engines.AnalyticEuropeanEngine(model)`, and the free function
`black_scholes(option_type, strike, inputs)` that solvers and other engines (control
variates in Monte Carlo) call directly. Result: `BlackScholesValuation` (`npv`, `forward`,
`d1`, `d2`, `greeks`).

```python
from pricer.engines import AnalyticEuropeanEngine
from pricer.models import BlackScholesModel

engine = AnalyticEuropeanEngine(BlackScholesModel("USD-TSY", dividend_curve="SPX-DIV"))
# value = engine.price(option, snapshot); value.npv, value.greeks.delta, ...
```

`examples/price_option.py` prices a one-year index call and put end to end.

## Greeks

The Greeks are the partial derivatives of $V$, with $\varphi$ the standard normal density and
$r = -\ln D_r / T$, $q = -\ln D_q / T$ the zero rates to expiry. The identity
$S D_q\,\varphi(d_1) = K D_r\,\varphi(d_2)$ cancels every term coming from the derivatives of
$d_1$ and $d_2$, which is why they are so compact.

| Greek | Formula | Meaning | Sign (long option) |
|---|---|---|---|
| Delta $\partial V/\partial S$ | $\omega D_q N(\omega d_1)$ | Hedge ratio, shares per option | call $\in [0, D_q]$, put $\in [-D_q, 0]$ |
| Gamma $\partial^2 V/\partial S^2$ | $\dfrac{D_q\,\varphi(d_1)}{S \sigma \sqrt{T}}$ | How fast delta moves; cost of re-hedging | $\ge 0$, same for call and put |
| Vega $\partial V/\partial \sigma$ | $S D_q\,\varphi(d_1)\sqrt{T}$ | Exposure to implied volatility | $\ge 0$, same for call and put |
| Theta $\partial V/\partial t$ | $-\dfrac{S D_q\,\varphi(d_1)\,\sigma}{2\sqrt{T}} + \omega\big(q S D_q N(\omega d_1) - r K D_r N(\omega d_2)\big)$ | Time decay | usually $< 0$ |
| Rho $\partial V/\partial r$ | $\omega K T D_r N(\omega d_2)$ | Rate exposure | call $> 0$, put $< 0$ |
| Dividend rho $\partial V/\partial q$ | $-\omega S T D_q N(\omega d_1)$ | Dividend / repo exposure | call $< 0$, put $> 0$ |

**Units.** Every Greek is a raw partial derivative per unit of the risk factor, as in
QuantLib (`pricer.greeks.Greeks`). Desks quote vega per vol point ($\text{vega}/100$), rho per
basis point ($\text{rho}/10^4$) and theta per day (`theta_per_day` $= \theta/365$).

**Theta convention.** Theta is the change in value as calendar time passes, holding the
spot, the volatility and the zero rates $r$, $q$ *to expiry* fixed. With a sloped curve,
another convention (holding the forward curve fixed, so the zero rate to expiry rolls down
the curve) gives a slightly different number; ours is QuantLib's. The bump-and-revalue theta
uses the other one, see [Greeks by bump](option-risk.md#bump-and-revalue-greeks).

**Rho and the curve.** Rho is the sensitivity to the zero rate to expiry, which is exactly
what a parallel shift of the discount curve moves. The unit tests check that rho equals the
value change under a `ZeroSpreadedCurve` bump, so the analytic Greek and the risk service's
bump agree.

## Relations every price must satisfy

These are tested on random inputs (hypothesis) on top of the QuantLib benchmark:

- **Put-call parity**: $C - P = S D_q - K D_r$. A call minus a put is a forward, whose value
  does not depend on any model. Consequences: $\Delta_C - \Delta_P = D_q$,
  $\Gamma_C = \Gamma_P$, $\text{vega}_C = \text{vega}_P$.
- **No-arbitrage bounds**: $\max(S D_q - K D_r, 0) \le C \le S D_q$ and
  $\max(K D_r - S D_q, 0) \le P \le K D_r$.
- **Strike monotonicity and convexity**: the call price decreases in $K$ (a call spread has a
  non-negative payoff) and is convex in $K$ (so is a butterfly). Convexity in strike is what
  makes the risk-neutral density $\partial^2 C/\partial K^2 / D_r$ non-negative.
- **The Black-Scholes PDE**: $\Theta + (r - q) S \Delta + \tfrac12 \sigma^2 S^2 \Gamma - r V = 0$.
  This links the time decay to gamma: a delta-hedged long option loses theta and earns
  gamma, and the two balance exactly when realised volatility equals $\sigma$.

## Degenerate cases

When $\sigma\sqrt{T} = 0$ (the option expires today, or zero volatility), $S_T = F$ is known:
the value is $D_r \max(\omega(F - K), 0)$ and the Greeks are those of that expression (delta is
a step, gamma and vega are zero). An option expiring on the valuation date is therefore
worth its payoff; an option that expired before is rejected with a `PricerError`. The tests
check that these values are the limit of the general formula as $\sigma \to 0$.

## Limits of the model

- **Constant volatility.** Market prices imply a different $\sigma$ per strike and expiry
  (smile and term structure). The engine reads $\sigma(T, K)$ from a `VolatilitySurface`, so
  it prices off a smile once one exists, but the *dynamics* stay lognormal: the Greeks ignore
  how the smile moves with the spot (sticky-strike vs sticky-delta). Heston (phase 3) is the
  answer on the model side.
- **Continuous dividend yield.** Single stocks pay discrete cash dividends; a yield curve
  approximates them well for an index, less well for a stock with one large dividend.
- **No jumps, continuous hedging, no transaction costs.** The replication argument assumes
  all three. Gamma is the measure of how much the real-world hedging error costs.
- **European exercise only.** American options are priced on the
  [CRR tree](american-options.md).

## Validation

| Check | Where | Result |
|---|---|---|
| Textbook example (Hull: $S=42$, $K=40$, $r=10\%$, $\sigma=20\%$, $T=0.5$) | `tests/engines/test_analytic_european.py` | $c = 4.76$, $p = 0.81$, $d_1$ and $d_2$ to $10^{-4}$ |
| At-the-money-forward closed form $V = D_r F\,\mathrm{erf}\big(\sigma\sqrt{T}/(2\sqrt{2})\big)$ | same | $10^{-14}$ relative |
| Parity, bounds, strike convexity, PDE | same (hypothesis) | exact up to rounding |
| Greeks vs central finite differences, and vs snapshot bumps | same | $10^{-6}$ / $10^{-7}$ relative |
| QuantLib `AnalyticEuropeanEngine`, 162 cases | `validation/test_european_option_quantlib.py` | price and 6 Greeks to $10^{-10}$ relative (observed $\le 1.1 \times 10^{-13}$) |

The QuantLib benchmark caught a missing $1/S$ in the first version of gamma, which the
finite-difference test would also have caught: the reason both exist.
