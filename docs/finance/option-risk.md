# Greeks by bump and implied volatility

Two tools that sit on top of any option engine: Greeks computed by revaluing on bumped
markets, and the inversion of a quoted price into a volatility.

## Bump-and-revalue Greeks

A closed form gives exact Greeks, but a tree or a Monte Carlo engine only gives a price. The
universal method is to revalue on slightly modified markets and take finite differences.
`pricer.greeks.bump_greeks` does it from a `MarketSnapshot -> float` function, like
`parallel_dv01` for curves, so the same code serves every engine and the risk service bumps
exactly the market objects it receives.

| Greek | Bumped object | Scheme | Error |
|---|---|---|---|
| Delta | Spot $S(1 \pm h)$ | $\dfrac{V_+ - V_-}{2hS}$ | $O(h^2)$ |
| Gamma | Spot $S(1 \pm h)$ | $\dfrac{V_+ - 2V_0 + V_-}{(hS)^2}$ | $O(h^2)$ truncation, $\sim \varepsilon V / (hS)^2$ round-off |
| Vega | Volatility surface, parallel shift (`ShiftedVolatility`) | central | $O(h^2)$ |
| Rho, dividend rho | Zero rates of each curve (`ZeroSpreadedCurve`) | central | $O(h^2)$ |
| Theta | Whole market rolled forward by $n$ days (`MarketSnapshot.roll_forward`) | $\dfrac{V(t + n\text{d}) - V(t)}{n/365}$ | $O(n \text{ days})$ |

Code: `bump_greeks(value, market, underlying, discount_curve, dividend_curve=..., bumps=BumpSizes(...))`.
Defaults: spot 0.1% relative, volatility 0.01 vol point, rates 1bp, theta over one day.

```python
from pricer.greeks import bump_greeks

# greeks = bump_greeks(lambda m: engine.price(option, m).npv, snapshot, "SPX", "USD-TSY",
#                      dividend_curve="SPX-DIV")
```

**Choosing the bump size.** Too large, and the truncation error (the curvature of the value
between the bumps) dominates; too small, and the round-off of the difference does, worse for
gamma since it divides by $h^2$. For a closed form, $h = 10^{-3}$ relative is safely in the
middle. For a **tree**, the value is not smooth in the spot (the grid moves with it), so
bumps must be larger than a node spacing. For **Monte Carlo**, every bumped revaluation must
reuse the same random numbers (same seed: *common random numbers*); otherwise the difference
is dominated by noise of order $\text{stderr}/h$.

**Theta: two conventions.** Rolling the market one day can mean two things for the curves:

- *forwards realised* (`RolledCurve`): tomorrow's curve is today's forward curve,
  $P'(t) = P(\delta + t)/P(\delta)$. This is what the bump uses: the value change if nothing
  happens except time passing *as the market expects*;
- *zero rates fixed*: the zero rate to expiry stays the same. This is what the analytic
  Black-Scholes theta assumes (and QuantLib's).

On a flat curve they coincide. On a sloped curve they differ by about
$\text{rho} \times$ (roll-down of the zero rate to expiry per year); the tests check this
first-order decomposition. In `examples/price_option.py` (one-year index call), the analytic
theta is $-0.739$ per day and the one-day roll gives $-0.759$.

## Implied volatility

Options are quoted in volatility, not in price: a volatility is comparable across strikes,
expiries and underlyings. The implied volatility is the $\sigma$ such that the Black-Scholes
price equals the quoted price $V$.

**Existence and uniqueness.** The Black-Scholes price is continuous and strictly increasing
in $\sigma$ (vega $> 0$), from the discounted forward intrinsic value at $\sigma = 0$ to the
upper bound ($S D_q$ for a call, $K D_r$ for a put) as $\sigma \to \infty$. A solution exists,
and is unique, if and only if

$$
\max\big(\omega(S D_q - K D_r), 0\big) < V < \begin{cases} S D_q & \text{call} \\ K D_r & \text{put} \end{cases}
$$

Outside these bounds the price is an arbitrage, and the solver raises a `PricerError`
rather than returning a meaningless number.

**Solver.** Brent's method on $\sigma \in [0, \sigma_{\max}]$, with $\sigma_{\max}$ doubled
from 400% until it brackets the root (capped at 100,000%). Newton's method with the analytic
vega is faster near the money, but vega vanishes far from it and Newton then overshoots or
diverges; a bracketing method cannot fail on a valid price. Production systems inverting
millions of quotes use Jäckel's *Let's be rational* (machine precision in two iterations).

Code: `pricer.analytics.implied_volatility(option, price, model, market)`, which needs the
spot and the curves but no volatility surface, and the lower-level
`black_scholes_implied_volatility(option_type, strike, price, inputs)`.

**Accuracy is limited by vega.** A price known to $\varepsilon$ only determines $\sigma$ to
$\varepsilon / \text{vega}$. Far out of the money at low volatility, the time value can be
below double-precision noise: the price is numerically the intrinsic value and no
volatility can be implied. The QuantLib benchmark checks that the solver either rejects
such a price or returns a volatility that reprices it.

**Parity.** A call and a put of the same strike and expiry, consistent with put-call
parity, imply the same volatility. A smile is a function of strike and expiry, never of the
option type; a call/put implied-vol gap in market data means the forward (dividends,
borrow cost) is wrong.

## Validation

| Check | Where | Result |
|---|---|---|
| Bump Greeks vs analytic Greeks, flat and bootstrapped curves, 3 strikes, call/put | `tests/greeks/test_bump.py` | $10^{-4}$ relative (observed $\le 1.1 \times 10^{-5}$) |
| Bump theta on flat curves vs exact one-day value change | same | $10^{-10}$ relative |
| Bump theta vs analytic theta on a sloped curve | same | gap $=$ rho $\times$ roll-down, to 5% |
| `RolledCurve` keeps forward rates; flat curve rolls to itself | `tests/market/test_market_roll.py` | $10^{-12}$ |
| Implied vol round trip (hypothesis), call/put parity, bounds, very high vol | `tests/analytics/test_implied_volatility.py` | $10^{-12}$ (scaled by $1/\text{vega}$) |
| QuantLib `impliedVolatility`, 90 cases (5 strikes × 3 expiries × 3 vols × call/put) | `validation/test_implied_volatility_quantlib.py` | $10^{-10}$; observed $\le 3.1 \times 10^{-12}$ from the true vol |
