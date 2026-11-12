# ADR 0002 — Option models: a binding to the snapshot, consumed by every engine

- Status: accepted
- Date: 2026-11-12

## Context

Phase 2 adds options and three numerical methods for the same model (closed form, CRR
tree, Monte Carlo). The architecture requires instruments, models and engines to be
separate, and market data to come from one immutable `MarketSnapshot`. We need to decide
what a "model" object is when its parameters (spot, rates, dividend yield, volatility) are
market data that already live in the snapshot.

## Decision

**A model is a frozen binding, not a container of market data.**
`BlackScholesModel(discount_curve, dividend_curve=None, day_count=ACT_365F)` names the
curves playing the roles of $r$ and $q$. The spot and the volatility surface are looked up
under the instrument's underlying identifier.

**The model resolves the inputs; engines only compute.**
`BlackScholesModel.inputs(underlying, expiry, strike, market)` returns a frozen
`BlackScholesInputs` (spot, $T$, $D_r(T)$, $D_q(T)$, $\sigma(T, K)$). Every Black-Scholes
engine (analytic now; tree and Monte Carlo next) is constructed with a model and calls
`inputs`, so all of them price *the same* model by construction, and the convergence tests
compare methods, not set-ups.

**The closed form is written on the forward** ($F = S D_q / D_r$), with discount factors
rather than flat rates. Any deterministic term structure of $r$ and $q$ is then exact for a
European option, without a "flat rate equivalent" approximation.

**Greeks are raw partial derivatives** (`pricer.greeks.Greeks`), QuantLib units; quoting
units (per vol point, per bp, per day) are derived.

## Alternatives rejected

- **Model holding numbers** (`BlackScholesModel(spot, r, q, sigma)`): duplicates the
  snapshot, so bump-and-revalue Greeks would have to bump two places, and a persisted
  snapshot would no longer be enough to reproduce a price.
- **Engine reading the snapshot directly** (curve names on the engine, as for bonds): fine
  for one engine, but three engines would each re-implement the lookup and the time
  convention, and could silently disagree.
- **Flat rates `r`, `q`** as inputs: simpler formulas, but wrong as soon as the curve is not
  flat, unless the zero rate to expiry is used, which is what the forward form does
  implicitly.

## Consequences

- Adding Heston (phase 3) is a new model with its own inputs and its own engines; the
  Black-Scholes classes do not change.
- A smile is supported as soon as a `VolatilitySurface` with strike dependence exists: the
  model already passes $(T, K)$.
- Theta is defined at fixed zero rates to expiry (QuantLib's convention), documented in
  [Black-Scholes](../finance/black-scholes.md#greeks).
