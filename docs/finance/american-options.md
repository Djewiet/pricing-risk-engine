# American options and the binomial tree

## Product

An **American** option can be exercised on any day up to its expiry, a European one only
at expiry. The holder of an American option exercises when the payoff
$\max(\omega(S - K), 0)$ is worth more than keeping the option alive. Most listed single-stock
options are American; index options are usually European.

Code: `pricer.instruments.AmericanOption` and `EuropeanOption`, both `VanillaOption`s with
the same terms (underlying, strike, expiry, type). The exercise style is a contract term,
`early_exercise`, read by the engine at each node: one engine serves both styles without
testing the class of the instrument.

## When is early exercise worth anything?

Two arbitrage arguments, both checked exactly by the tests:

- **A call on a stock without dividends is never exercised early** (Merton, 1973), as long as
  $r \ge 0$. Alive, it is worth at least $S - K D_r \ge S - K$, its exercise value: exercising
  throws away the time value and pays the strike early. So American call = European call.
  With dividends ($q > 0$), exercising just before the stock pays captures them, and early
  exercise can be optimal.
- **A put is exercised early when it is deep in the money** and $r > 0$: receiving $K$ now
  and earning interest on it beats waiting for a payoff capped at $K$. With $r \le 0$ the
  argument reverses, and the American put is worth the European put.

The difference American − European is the **early exercise premium**. In
`examples/price_option.py`, a one-year 6100 put on an index at 6000 is worth 404.40 European
and 419.39 American.

There is no closed form for the American put: the optimal exercise boundary $S^*(t)$, below
which the holder exercises, is part of the solution (a free-boundary problem). Hence a
numerical method.

## The Cox-Ross-Rubinstein tree

Cut $[0, T]$ into $N$ steps of $\Delta t = T/N$. Over one step the spot moves up by
$u = e^{\sigma\sqrt{\Delta t}}$ or down by $d = 1/u$, so the tree recombines: after $i$ steps
there are $i + 1$ nodes $S\,u^{2j - i}$. The up probability

$$
p = \frac{e^{(r - q)\Delta t} - d}{u - d}
$$

is the risk-neutral one: it makes the expected spot grow at $r - q$ on each step, so the tree
prices the forward exactly. $u$ and $d$ match the variance $\sigma^2 \Delta t$; as
$N \to \infty$ the terminal distribution converges to the Black-Scholes lognormal.

**Backward induction.** Start from the payoff at the $N + 1$ terminal nodes, and step back:

$$
V_{i,j} = e^{-r\Delta t}\big(p\,V_{i+1,j+1} + (1 - p)\,V_{i+1,j}\big),
\qquad
V_{i,j} \leftarrow \max\big(V_{i,j}, \text{payoff}(S_{i,j})\big) \text{ if American.}
$$

Each step is one NumPy operation on the vector of nodes, so $N = 1000$ takes about 15 ms
($O(N^2)$ work, no Python loop over nodes).

**Rates.** The tree uses constant rates, the zero rates to expiry
$r = -\ln D_r(T)/T$ and $q = -\ln D_q(T)/T$, from the same `BlackScholesModel` as the
closed form. This is exact for a European option and an approximation for an American one
under a sloped curve (the early-exercise decision at time $t$ depends on the forward rates
after $t$), as in QuantLib's tree engines.

**Validity.** $p$ must lie in $(0, 1)$, or the tree is an arbitrage. This fails when
$\sigma\sqrt{\Delta t} < |r - q|\Delta t$, i.e. at low volatility with few steps; the engine
raises a `PricerError` rather than returning a price.

Code: `pricer.engines.BinomialTreeEngine(model, steps=500)` and the free function
`binomial_tree(option, inputs, steps)`. Result: `TreeValuation` (`npv`, `delta`, `gamma`,
`theta`, `steps`).

## Greeks from the tree

The first two steps of the tree already contain the neighbouring scenarios (Hull):

- delta $= \dfrac{V_{1,1} - V_{1,0}}{S u - S d}$;
- gamma: difference of the two deltas at step 2, divided by $\tfrac12(S u^2 - S d^2)$;
- theta $= \dfrac{V_{2,1} - V_{0,0}}{2\Delta t}$, since the middle node at step 2 has the
  spot of the root ($u d = 1$).

They cost nothing extra. Vega and rho need a revaluation: `bump_greeks` provides them, as
for any engine. Because the nodes move with the inputs, a tree's value is not smooth in
$\sigma$ or $S$: bumps must be large compared with the node spacing.

**A difference with QuantLib.** QuantLib computes its tree theta from the Black-Scholes PDE,
$\Theta = rV - (r-q)S\Delta - \tfrac12\sigma^2S^2\Gamma$. The PDE only holds where the option
is *not* exercised. For an option exercised immediately ($V = $ payoff), our theta is 0, the
value does not change with time, while QuantLib reports $\omega(qS - rK)$. The validation
suite records this as a difference of definition.

## Convergence

The CRR price converges to Black-Scholes in $O(1/N)$, and **oscillates** with $N$: the
strike falls at a different place between terminal nodes depending on the parity of $N$
(and on $N$ itself), which moves the discretised payoff. Comparing steps of the same parity
gives a clean $1/N$ decay; the tests check that quadrupling $N$ divides the error by more
than 2. Improvements (out of scope for now): smoothing the last step with the Black-Scholes
formula, Richardson extrapolation over $N$ and $2N$, or the Leisen-Reimer tree (order 2).
The convergence study and plots are part of the validation report (phase 2, step 5).

## Validation

| Check | Where | Result |
|---|---|---|
| European tree → Black-Scholes, 3 strikes × call/put | `tests/engines/test_binomial.py` | error $< 5 \times 10^{-3}$ at $N = 2000$, divided by $> 2$ from $N = 500$ |
| European tree put-call parity (hypothesis) | same | exact to rounding, at any $N$ |
| American ≥ max(European, payoff) (hypothesis) | same | holds |
| American call, $q = 0$, $r \ge 0$; American put, $r < 0$ | same | equal to European to $10^{-12}$ |
| Deep in-the-money American put | same | $K - S$, delta $-1$, gamma 0 |
| American value increasing in maturity (hypothesis) | same | holds |
| QuantLib `BinomialVanillaEngine("crr")`, 144 American + 144 European cases, $N = 1000$ | `validation/test_american_option_quantlib.py` | price $3 \times 10^{-3}$ (observed $1.6 \times 10^{-3}$), delta $10^{-4}$: QuantLib's $p$ is a first-order expansion of ours, so the gap is $O(1/N)$ |
| QuantLib `FdBlackScholesVanillaEngine` (PDE solver), 24 American cases | same | $5 \times 10^{-3}$: a different numerical method |
