# Data flow

## From quotes to risk numbers

```mermaid
flowchart LR
    subgraph inputs["Inputs"]
        CSV["Treasury CSV"]
        TERMS["Contract terms<br/>issue, maturity, coupon"]
    end
    subgraph market["Market data (immutable)"]
        Q["ParYieldQuote[]"]
        DC["DiscountCurve<br/>pillars: dates, DFs"]
        MS["MarketSnapshot<br/>timestamp, valuation date,<br/>curves, spots, vols"]
    end
    subgraph pricing["Pricing"]
        FRB["FixedRateBond<br/>cash flows, accrued"]
        ENG["DiscountingBondEngine<br/>curve_name"]
        BV["BondValuation<br/>npv, dirty, clean, accrued"]
    end
    subgraph measures["Measures"]
        YA["YieldAnalytics<br/>YTM, durations, convexity, DV01"]
        ZS["z-spread"]
        DV["curve DV01"]
    end

    CSV -- "parse_par_yield_csv" --> Q
    Q -- "bootstrap_par_yield_curve" --> DC
    DC --> MS
    TERMS --> FRB
    FRB --> ENG
    MS --> ENG
    ENG -- "price()" --> BV
    BV -- "clean price" --> YA
    BV -- "clean price" --> ZS
    DC --> ZS
    MS -- "with_curve(bumped)" --> DV
    ENG -- "repriced NPV" --> DV
```

Three properties of this flow matter:

1. **The snapshot is the only market input.** The engine receives the snapshot and looks
   up the curve by name (`curve_name="USD-TSY"`). Nothing reads market data from a global.
2. **Analytics work from a price, not from a market.** `yield_to_maturity` and
   `yield_analytics` take a bond, a price or yield, and a settlement date. They do not need
   a snapshot, which is why they live in `analytics/` and not in `engines/`.
3. **Risk is a higher-order function.** `parallel_dv01` takes a `MarketSnapshot -> float`
   function. It does not know about bonds: the same function will compute the DV01 of a
   swap or of a whole portfolio.

## Sequence of one pricing call

```mermaid
sequenceDiagram
    autonumber
    actor Caller
    participant Engine as DiscountingBondEngine
    participant Snap as MarketSnapshot
    participant Bond as FixedRateBond
    participant Curve as DiscountCurve

    Caller->>Engine: price(bond, snapshot)
    Engine->>Snap: curve("USD-TSY")
    Snap-->>Engine: YieldCurve (or MissingMarketDataError)
    Engine->>Bond: remaining_cashflows(settlement = curve.reference_date)
    Bond-->>Engine: coupons and redemption paid after settlement
    Engine->>Curve: time(d) for each payment date (ACT/365F)
    Engine->>Curve: discount_factors(times) [one vectorised call]
    Curve-->>Engine: exp(interp(ln P))
    Engine->>Engine: npv = amounts . discounts
    Engine->>Bond: accrued_interest(settlement)
    Bond-->>Engine: accrued per 100
    Engine-->>Caller: BondValuation(npv, dirty, clean, accrued)
```

Settlement is the curve reference date, which the snapshot guarantees is the valuation
date (T+0). A cash flow paid *on* the settlement date is excluded: it belongs to the seller.

## Sequence of a swap pricing

The swap engine follows the same pattern with two curve roles. In phase 1 both names point
to the same Treasury curve.

```mermaid
sequenceDiagram
    autonumber
    actor Caller
    participant Engine as DiscountingSwapEngine
    participant Snap as MarketSnapshot
    participant Swap as InterestRateSwap
    participant D as discount curve
    participant F as forecast curve

    Caller->>Engine: price(swap, snapshot)
    Engine->>Snap: curve(discount_curve), curve(forecast_curve)
    Engine->>Swap: fixed_leg, floating_leg (remaining coupons)
    Engine->>D: discount_factors(fixed payment times)
    Note over Engine: annuity A = N sum tau_i D(t_i), PV_fixed = K A
    Engine->>F: discount_factors(accrual starts and ends)
    Note over Engine: R_j = (F(s_j) / F(e_j) - 1) / tau_j
    Engine->>D: discount_factors(floating payment times)
    Note over Engine: PV_float = N sum (R_j + s) tau_j D(e_j)
    Engine-->>Caller: SwapValuation(npv, leg PVs, annuity, par rate)
```

## Sequence of a curve DV01

```mermaid
sequenceDiagram
    autonumber
    actor Caller
    participant Risk as parallel_dv01
    participant Snap as MarketSnapshot
    participant Value as value(m) = engine.price(bond, m).npv

    Caller->>Risk: parallel_dv01(value, snapshot, "USD-TSY")
    Risk->>Snap: curve("USD-TSY")
    Risk->>Snap: with_curve("USD-TSY", ZeroSpreadedCurve(curve, -1bp))
    Snap-->>Risk: new snapshot (down)
    Risk->>Value: value(down)
    Risk->>Snap: with_curve("USD-TSY", ZeroSpreadedCurve(curve, +1bp))
    Snap-->>Risk: new snapshot (up)
    Risk->>Value: value(up)
    Risk-->>Caller: (V_down - V_up) / 2
    Note over Snap: The base snapshot is never modified.
```

## Sequence of the bootstrap

```mermaid
sequenceDiagram
    autonumber
    participant Boot as bootstrap_par_yield_curve
    participant PB as _ParBond
    participant Solver as brentq
    participant Trial as DiscountCurve (trial)

    Boot->>PB: build(reference, maturity) for each quote
    Boot->>Boot: sort by maturity, reject duplicates
    loop each quote k, by increasing maturity
        Boot->>Solver: solve residual(z) = 0 on z in [-50%, 100%]
        loop Brent iterations
            Solver->>Trial: pillars 1..k-1 fixed, pillar k = exp(-z t_k)
            Trial-->>PB: discount factors of the coupon dates
            PB-->>Solver: par_yield(trial) - quote
        end
        Solver-->>Boot: z_k, then P_k = exp(-z_k t_k)
    end
    Boot-->>Boot: DiscountCurve(reference, pillars, DFs)
```
