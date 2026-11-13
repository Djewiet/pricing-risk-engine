# Roadmap

| Phase | Scope | Status |
|---|---|---|
| 1. Foundations | Repo, CI, dates, market data, yield curve bootstrap, bonds, swaps | Core done; calendars and key-rate DV01 remaining |
| 2. Options | Black-Scholes analytic, CRR tree (American), Monte Carlo (antithetic, control variates), Greeks, validation report | Done |
| 3. Heston and performance | Heston Monte Carlo; naive Python → NumPy → Numba kernels; multi-process portfolio repricing; pytest-benchmark tables | Planned |
| 4. Risk service | Simulated tick feed, Redis Streams consumer groups, worker pool, FastAPI + WebSocket, historical VaR, PostgreSQL | Planned |
| 5. Polish | Prometheus/Grafana, README GIF, report extended to Heston and VaR | Planned |

## Phase 1: remaining items

- **Business-day calendar** (US government bond) and adjustment conventions, so coupon
  and swap payment dates roll like real securities.
- **Key-rate DV01**: bump each par yield, re-bootstrap, reprice. Gives the curve-shape risk
  that the parallel DV01 hides.
- **Past fixings** in the snapshot, to price swaps whose floating coupon is already
  accruing.

## Phase 2: plan

| Step | Content | Status |
|---|---|---|
| 1 | `EuropeanOption`, `BlackScholesModel`, `AnalyticEuropeanEngine`, analytic Greeks, QuantLib benchmark | Done |
| 2 | Generic bump-and-revalue Greeks on any engine; implied volatility solver | Done |
| 3 | `AmericanOption`, CRR binomial tree (European and American), early-exercise properties | Done |
| 4 | Monte Carlo engine: vectorised GBM, seeded `Generator`, antithetic and control variates, standard errors | Done |
| 5 | Convergence studies (tree and Monte Carlo to the closed form) and the generated Model Validation Report | Done |

## Later (v2)

- Monotone-convex (Hagan–West) interpolation.
- Heston calibration to market data.
- SOFR curve from a licensed source.
