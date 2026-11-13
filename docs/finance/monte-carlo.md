# Monte Carlo pricing

## Principle

Under the risk-neutral measure, an option value is a discounted expectation,
$V = D_r\,E[\text{payoff}(S_T)]$. Monte Carlo estimates it by an average over $n$ simulated
scenarios:

$$
\hat V = \frac{1}{n}\sum_{i=1}^n Y_i, \qquad Y_i = D_r\,\text{payoff}(S_T^{(i)}),
\qquad \text{s.e.}(\hat V) = \frac{\text{stdev}(Y)}{\sqrt{n}}.
$$

By the central limit theorem, $\hat V$ is approximately normal around $V$, and
$\hat V \pm 1.96\,\text{s.e.}$ is a 95% confidence interval. The price of precision is
steep: halving the error costs four times the paths. Hence the variance reduction
techniques below, which shrink $\text{stdev}(Y)$ instead of growing $n$.

For a European vanilla, the closed form exists; the Monte Carlo engine is there to be
checked against it, and as the template for what has no closed form (Heston in phase 3,
path-dependent payoffs).

## Exact simulation

Under Black-Scholes, $S_T$ is lognormal, so it is sampled exactly in one step:

$$
S_T = F \exp\!\left(-\tfrac12 \sigma^2 T + \sigma\sqrt{T}\,Z\right), \qquad Z \sim N(0, 1),
$$

with $F = S D_q / D_r$ from the same `BlackScholesModel` as the other engines. There is no
time-discretisation error (an Euler scheme on $dS$ would add a bias of order $\Delta t$): the
estimator is **unbiased** and its only error is statistical. A path-dependent payoff or a
stochastic volatility will need a time grid; that is phase 3.

## Variance reduction

**Antithetic variates.** Each draw $Z$ is paired with $-Z$. For a payoff monotone in $Z$, the
two values are negatively correlated, so their average varies less than two independent
draws. The independent samples are now the $n/2$ pair averages, and the standard error must
be computed on them (computing it on the $n$ correlated values would understate it).

**Control variate.** The discounted terminal spot $X = D_r S_T$ has a known mean,
$E[X] = S D_q$. For any $\beta$,

$$
\hat V_\beta = \overline{Y} - \beta\,(\overline{X} - S D_q)
$$

is still unbiased, and its variance $\text{Var}(Y) - 2\beta\,\text{Cov}(X, Y) + \beta^2\text{Var}(X)$
is minimal at $\beta^* = \text{Cov}(X, Y)/\text{Var}(X)$, the regression slope of $Y$ on $X$.
The variance left is $(1 - \rho^2)\,\text{Var}(Y)$: the better the control tracks the payoff,
the larger the gain. An in-the-money call is almost linear in $S_T$, so the gain is huge.
$\beta^*$ is estimated on the same sample, which adds a bias of order $1/n$, negligible
against the $1/\sqrt n$ statistical error.

Variance gains on a one-year call ($S = 100$, $\sigma = 25\%$), both techniques combined, for
the same number of paths (`tests/engines/test_monte_carlo.py`):

| Strike | 80 (in the money) | 100 | 130 (out of the money) |
|---|---|---|---|
| Variance ratio plain / reduced | 458 | 25 | 20 |

A factor 458 in variance is the same precision as 458 times more paths.

**Put-call parity becomes exact.** $Y_{\text{call}} - Y_{\text{put}} = X - K D_r$ is linear in
the control, so the two regressions differ by exactly $\beta = 1$ and leave identical
residuals: the Monte Carlo errors of the call and the put cancel, and
$\hat C - \hat P = S D_q - K D_r$ to rounding, even with 1,000 paths. The tests check it.

## Randomness and reproducibility

Randomness comes only from an explicitly passed `numpy.random.Generator`; there is no global
random state. The engine holds a **seed**, not a generator, and builds a fresh generator for
each valuation:

- a valuation is a pure function of (option, market, engine): pricing twice gives the same
  number, and a result can be reproduced from the persisted snapshot;
- bump-and-revalue Greeks reuse the same random numbers for every bumped market
  (**common random numbers**). The noise is then the same in $V(S + h)$ and $V(S - h)$ and
  cancels in the difference. With independent draws, a delta by bump would be noise of order
  $\text{s.e.}/h$; with common random numbers it is within 1% of the analytic delta
  (`test_bump_greeks_with_common_random_numbers`).

Gamma by bump stays noisy, because the payoff has a kink at the strike. The standard
remedies are pathwise derivatives and the likelihood-ratio method; out of scope here.

Code: `pricer.engines.MonteCarloEuropeanEngine(model, paths=100_000, seed=..., antithetic=True, control_variate=True)`
and the free function `monte_carlo_european(option, inputs, paths, rng, ...)`. Result:
`MonteCarloValuation` (`npv`, `std_error`, `paths`, `control_beta`, `confidence_interval(z)`).

## Performance

Everything is vectorised: one draw of $n$ normals, one exponential, one payoff call, no
Python loop over paths. 1,000,000 paths take about 40 ms; memory is about 24 bytes per path.
Phase 3 implements the kernel three ways (naive Python loop, NumPy, Numba with
`parallel=True`) and benchmarks them.

## Validation

A Monte Carlo price is a random variable, so it is validated on its **error model**, not
against a fixed tolerance.

| Check | Where | Result |
|---|---|---|
| Estimate within 4 standard errors of Black-Scholes, 3 strikes × call/put × 4 variance-reduction settings | `tests/engines/test_monte_carlo.py` | holds (fixed seeds: deterministic) |
| Standard error × 1/4 for 16 × the paths | same | within 5% |
| Each technique reduces the variance; combined gain | same | see table above |
| Put-call parity with the control variate | same | exact to $10^{-12}$ |
| Zero volatility, expiry today, reproducibility | same | deterministic values |
| Delta, vega, rho by bump with common random numbers | same | within 1% of analytic |
| Convergence order of the RMSE and of the standard error, per variance-reduction setting | `validation/test_convergence.py` | slopes near $-1/2$ ([plot](../validation-report/index.md#convergence-of-monte-carlo)) |
| **Coverage of the 95% confidence interval** over 400 independent seeds, 24 cases, against QuantLib's closed form | `validation/test_monte_carlo_statistics.py` | coverage within the band 91.7%–98.3%; mean of $z$ within $\pm 0.2$; variance of $z$ 0.75 to 1.3 ([observed values](../validation-report/index.md#monte-carlo-error-model)) |

The coverage test is the one that would catch the classic mistakes: a biased estimator
shifts the mean of $z$, and a standard error computed on correlated antithetic values
(instead of the pair averages) makes the intervals too narrow and the coverage collapse.
