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

Black-Scholes
:   Model in which the underlying follows a geometric Brownian motion with constant
    volatility; gives closed-form prices for European options.

Bump and revalue
:   Computing a sensitivity by repricing on a slightly modified market and taking a finite
    difference. Works with every pricing method.

Call / put
:   Right to buy / sell the underlying at the strike. European: exercisable at expiry only;
    American: at any time up to expiry.

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

Forward price
:   $F = S D_q / D_r$: the delivery price that makes a forward contract worth zero today.

Forward rate
:   Rate for a future period implied today by no-arbitrage: $P(t_1)/P(t_2)$.

Greeks
:   Sensitivities of an option value: delta (spot), gamma (delta to spot), vega
    (volatility), theta (time), rho (rate), dividend rho (dividend yield).

Moneyness
:   Position of the strike relative to the spot or forward: in, at or out of the money.

OIS
:   Overnight Index Swap: a swap whose floating leg compounds an overnight rate (SOFR, €STR).

Par yield / par rate
:   Coupon (bond) or fixed rate (swap) that makes the instrument worth par / zero.

Payer / receiver
:   Pays / receives the fixed leg of a swap.

Put-call parity
:   $C - P = S D_q - K D_r$: a call minus a put is a forward. Holds in every model.

Pillar
:   A node of the curve where the discount factor is solved; interpolation in between.

Roll-down
:   Change of the zero rate to a fixed date as time passes along a sloped curve.

Settlement date
:   Date the trade is exchanged against cash; price and accrued interest refer to it.

SOFR
:   Secured Overnight Financing Rate, the USD overnight benchmark since the end of Libor.

Stub
:   Irregular (shorter or longer) coupon period, at the start of a backward schedule.

Strike
:   Price at which an option lets its holder buy (call) or sell (put) the underlying.

Tenor
:   Length of time in calendar units: 6M, 10Y.

Volatility
:   Annualised standard deviation of log-returns of the underlying. *Implied* volatility is
    the value that makes the Black-Scholes price equal the market price.

Yield to maturity
:   The single rate that discounts all cash flows back to the market price.

Z-spread
:   Constant shift of the zero curve that reprices a bond at its market price.

Zero rate
:   $z(t) = -\ln P(0,t)/t$: the constant continuous rate equivalent to $P(0,t)$.
