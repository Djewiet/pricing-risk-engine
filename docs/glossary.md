# Glossary

Accrued interest
:   Part of the current coupon earned by the seller since the last coupon date; paid by the
    buyer on top of the clean price.

Annuity
:   $A = \sum_i N \tau_i P(t_i)$: present value of receiving one unit of rate on a fixed
    leg. Converts a rate difference into a value.

Bootstrap
:   Building a curve pillar by pillar so that it reprices each quoted instrument exactly.

Clean / dirty price
:   Dirty (full) price is what is paid; clean price = dirty − accrued interest, and is
    what the market quotes.

Convexity
:   $P''(y)/P$: curvature of the price-yield relation.

Day count
:   Convention turning a date interval into a year fraction (ACT/360, ACT/ACT ICMA...).

Discount factor
:   $P(0,t)$: value today of one unit paid at $t$.

Duration (Macaulay, modified)
:   PV-weighted average time of the cash flows; relative price sensitivity to the yield.

DV01 / PV01
:   Value change for a 1 bp move: of the yield (yield DV01), of the zero curve (curve
    DV01), or of the fixed rate (PV01 of a swap, $A \times 10^{-4}$).

Forecast / discount curve
:   The curve projecting a floating index vs the curve discounting cash flows (the
    collateral rate). Equal in a single-curve setup.

Forward rate
:   Rate for a future period implied today by no-arbitrage: $P(t_1)/P(t_2)$.

OIS
:   Overnight Index Swap: a swap whose floating leg compounds an overnight rate (SOFR, €STR).

Par yield / par rate
:   Coupon (bond) or fixed rate (swap) that makes the instrument worth par / zero.

Payer / receiver
:   Pays / receives the fixed leg of a swap.

Pillar
:   A node of the curve where the discount factor is solved; interpolation in between.

Settlement date
:   Date the trade is exchanged against cash; price and accrued interest refer to it.

SOFR
:   Secured Overnight Financing Rate, the USD overnight benchmark since the end of Libor.

Stub
:   Irregular (shorter or longer) coupon period, at the start of a backward schedule.

Tenor
:   Length of time in calendar units: 6M, 10Y.

Yield to maturity
:   The single rate that discounts all cash flows back to the market price.

Z-spread
:   Constant shift of the zero curve that reprices a bond at its market price.

Zero rate
:   $z(t) = -\ln P(0,t)/t$: the constant continuous rate equivalent to $P(0,t)$.
