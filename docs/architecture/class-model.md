# Class model

## Core types

```mermaid
classDiagram
    direction LR

    class DayCount {
        <<Protocol>>
        +name str
        +year_fraction(start, end, ref_start, ref_end) float
    }
    class YieldCurve {
        <<abstract>>
        +reference_date date
        +day_count DayCount
        +discount_factors(times ndarray)* ndarray
        +time(d) float
        +discount(d) float
        +zero_rate(d, compounding, frequency) float
        +forward_rate(start, end, compounding, frequency) float
    }
    class FlatForwardCurve {
        +reference date
        +rate float
    }
    class DiscountCurve {
        +reference date
        +pillar_dates tuple~date~
        +pillar_discounts tuple~float~
        +pillar_times ndarray
    }
    class ZeroSpreadedCurve {
        +base YieldCurve
        +spread float
    }
    class VolatilitySurface {
        <<Protocol>>
        +black_vol(t, strike) float
    }
    class FlatVolatility {
        +sigma float
    }
    class MarketSnapshot {
        <<frozen>>
        +timestamp datetime
        +valuation_date date
        +curves Mapping~str, YieldCurve~
        +spots Mapping~str, float~
        +volatilities Mapping~str, VolatilitySurface~
        +curve(name) YieldCurve
        +with_curve(name, curve) MarketSnapshot
        +with_spot(name, spot) MarketSnapshot
    }

    YieldCurve <|-- FlatForwardCurve
    YieldCurve <|-- DiscountCurve
    YieldCurve <|-- ZeroSpreadedCurve
    ZeroSpreadedCurve o-- YieldCurve : wraps
    YieldCurve --> DayCount : time axis
    VolatilitySurface <|.. FlatVolatility
    MarketSnapshot o-- YieldCurve
    MarketSnapshot o-- VolatilitySurface
```

```mermaid
classDiagram
    direction LR

    class PricingEngine~InstrumentT, ResultT~ {
        <<Protocol>>
        +price(instrument, market) ResultT
    }
    class DiscountingBondEngine {
        <<frozen>>
        +curve_name str
        +price(bond, market) BondValuation
    }
    class BondValuation {
        <<frozen>>
        +settlement_date date
        +npv float
        +dirty_price float
        +clean_price float
        +accrued_interest float
    }
    class FixedRateBond {
        <<frozen>>
        +issue_date date
        +maturity date
        +coupon_rate float
        +frequency int
        +day_count DayCount
        +face_amount float
        +coupons tuple~FixedCoupon~
        +cashflows tuple~Cashflow~
        +remaining_cashflows(settlement)
        +accrued_interest(settlement) float
    }
    class Schedule {
        +effective date
        +maturity date
        +tenor Tenor
        +periods tuple~Period~
    }
    class Period {
        +start date
        +end date
        +ref_start date
        +ref_end date
    }
    class FixedCoupon {
        +payment_date date
        +amount float
        +accrual float
    }
    class Redemption {
        +payment_date date
        +amount float
    }
    class MarketSnapshot

    PricingEngine <|.. DiscountingBondEngine
    DiscountingBondEngine ..> FixedRateBond : prices
    DiscountingBondEngine ..> MarketSnapshot : reads curve
    DiscountingBondEngine ..> BondValuation : returns
    FixedRateBond ..> Schedule : generates
    Schedule *-- Period
    FixedRateBond *-- FixedCoupon
    FixedRateBond *-- Redemption
```

## Reading the diagrams

- **`YieldCurve` is a Template Method.** Subclasses implement one vectorised primitive,
  `discount_factors`; zero rates, forwards and date-based lookups are derived once in the
  base class. A new curve type (monotone-convex, Nelson-Siegel) is one method.
- **`ZeroSpreadedCurve` is a Decorator.** It wraps any curve and multiplies its discount
  factors by \(e^{-st}\). The parallel bump of the DV01 and the z-spread both use it, and the
  shift is exact at every \(t\), whatever the base interpolation.
- **Protocols, not base classes, at the edges.** `DayCount`, `VolatilitySurface` and
  `PricingEngine` are structural types: any object with the right method qualifies, with no
  inheritance coupling.
- **Frozen dataclasses everywhere.** Instruments, snapshots, results and engines are
  immutable; `DiscountCurve` also freezes its NumPy arrays (`setflags(write=False)`).
- **`PricingEngine` is generic in its result.** A bond engine returns `BondValuation`, an
  option engine will return a price with Greeks: one protocol, typed per engine.

## Swap

```mermaid
classDiagram
    direction LR
    class PricingEngine~InstrumentT, ResultT~ {
        <<Protocol>>
        +price(instrument, market) ResultT
    }
    class InterestRateSwap {
        <<frozen>>
        +effective_date date
        +maturity date
        +fixed_rate float
        +notional float
        +direction SwapDirection
        +fixed_tenor Tenor
        +fixed_day_count DayCount
        +floating_tenor Tenor
        +floating_day_count DayCount
        +floating_spread float
        +fixed_leg tuple~FixedCoupon~
        +floating_leg tuple~OvernightCoupon~
    }
    class SwapDirection {
        <<enumeration>>
        PAYER
        RECEIVER
        +sign int
    }
    class OvernightCoupon {
        +payment_date date
        +nominal float
        +accrual_start date
        +accrual_end date
        +accrual float
        +spread float
    }
    class DiscountingSwapEngine {
        <<frozen>>
        +discount_curve str
        +forecast_curve str
        +price(swap, market) SwapValuation
    }
    class SwapValuation {
        <<frozen>>
        +valuation_date date
        +npv float
        +fixed_leg_pv float
        +floating_leg_pv float
        +annuity float
        +par_rate float
    }
    class Schedule
    class FixedCoupon

    PricingEngine <|.. DiscountingSwapEngine
    DiscountingSwapEngine ..> InterestRateSwap : prices
    DiscountingSwapEngine ..> SwapValuation : returns
    InterestRateSwap --> SwapDirection
    InterestRateSwap ..> Schedule : generates both legs
    InterestRateSwap *-- FixedCoupon : fixed leg
    InterestRateSwap *-- OvernightCoupon : floating leg
```

None of the existing classes changed to add the swap: it reuses `Schedule`, `DayCount`,
`FixedCoupon`, `YieldCurve` and `MarketSnapshot`, and `parallel_dv01` applies to it
unchanged. The engine takes two curve names instead of one: the curve *roles* are part of
the engine, not of the instrument.

## European option

```mermaid
classDiagram
    direction LR
    class PricingEngine~InstrumentT, ResultT~ {
        <<Protocol>>
        +price(instrument, market) ResultT
    }
    class EuropeanOption {
        <<frozen>>
        +underlying str
        +strike float
        +expiry date
        +option_type OptionType
        +payoff(spots ndarray) ndarray
        +is_expired(valuation_date) bool
    }
    class OptionType {
        <<enumeration>>
        CALL
        PUT
        +sign int
    }
    class BlackScholesModel {
        <<frozen>>
        +discount_curve str
        +dividend_curve str | None
        +day_count DayCount
        +inputs(underlying, expiry, strike, market) BlackScholesInputs
    }
    class BlackScholesInputs {
        <<frozen>>
        +spot float
        +time_to_expiry float
        +discount_factor float
        +dividend_discount_factor float
        +volatility float
        +forward float
        +rate float
        +dividend_yield float
    }
    class AnalyticEuropeanEngine {
        <<frozen>>
        +model BlackScholesModel
        +price(option, market) BlackScholesValuation
    }
    class BlackScholesValuation {
        <<frozen>>
        +npv float
        +forward float
        +d1 float
        +d2 float
        +greeks Greeks
    }
    class Greeks {
        <<frozen>>
        +delta float
        +gamma float
        +vega float
        +theta float
        +rho float
        +dividend_rho float
        +theta_per_day float
    }
    class MarketSnapshot

    PricingEngine <|.. AnalyticEuropeanEngine
    AnalyticEuropeanEngine o-- BlackScholesModel
    AnalyticEuropeanEngine ..> EuropeanOption : prices
    AnalyticEuropeanEngine ..> BlackScholesValuation : returns
    BlackScholesModel ..> MarketSnapshot : reads spot, curves, vol
    BlackScholesModel ..> BlackScholesInputs : resolves
    EuropeanOption --> OptionType
    BlackScholesValuation *-- Greeks
```

The option introduces the third leg of the architecture. The **model** knows which curves
of the snapshot play the risk-free and dividend roles and turns the snapshot into
`BlackScholesInputs`; the **engine** only applies a formula to those inputs. The tree and
Monte Carlo engines of phase 2 take the same model, so the three methods price one model
by construction ([ADR 0002](../adr/0002-option-model-binding.md)).

## American option and the binomial tree

```mermaid
classDiagram
    direction LR
    class VanillaOption {
        <<frozen, abstract>>
        +early_exercise bool$
        +underlying str
        +strike float
        +expiry date
        +option_type OptionType
        +payoff(spots ndarray) ndarray
    }
    class EuropeanOption {
        +early_exercise = False$
    }
    class AmericanOption {
        +early_exercise = True$
    }
    class BinomialTreeEngine {
        <<frozen>>
        +model BlackScholesModel
        +steps int
        +price(option, market) TreeValuation
    }
    class TreeValuation {
        <<frozen>>
        +npv float
        +delta float
        +gamma float
        +theta float
        +steps int
    }
    class BlackScholesModel

    VanillaOption <|-- EuropeanOption
    VanillaOption <|-- AmericanOption
    BinomialTreeEngine o-- BlackScholesModel
    BinomialTreeEngine ..> VanillaOption : prices both styles
    BinomialTreeEngine ..> TreeValuation : returns
```

The exercise style is a class-level contract term, `early_exercise`. The tree engine reads
it at each node (`max(continuation, payoff)` when it is true) instead of testing the class
of the instrument, so a Bermudan option (exercise on a list of dates) would add a term,
not a branch. The analytic engine stays typed on `EuropeanOption`: mypy rejects pricing an
American option in closed form.

## Monte Carlo engine

```mermaid
classDiagram
    direction LR
    class MonteCarloEuropeanEngine {
        <<frozen>>
        +model BlackScholesModel
        +paths int
        +seed int
        +antithetic bool
        +control_variate bool
        +price(option, market) MonteCarloValuation
    }
    class MonteCarloValuation {
        <<frozen>>
        +npv float
        +std_error float
        +paths int
        +control_beta float
        +confidence_interval(z) tuple
    }
    class BlackScholesModel
    class EuropeanOption

    MonteCarloEuropeanEngine o-- BlackScholesModel
    MonteCarloEuropeanEngine ..> EuropeanOption : prices
    MonteCarloEuropeanEngine ..> MonteCarloValuation : returns
```

The three option engines (`AnalyticEuropeanEngine`, `BinomialTreeEngine`,
`MonteCarloEuropeanEngine`) share one model and differ only in the numerical method; each
returns its own result type, because a Monte Carlo price comes with a standard error and a
tree price with a number of steps. The Monte Carlo engine holds a *seed*: a frozen engine
must give the same number every time it is called.
