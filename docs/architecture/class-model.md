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
