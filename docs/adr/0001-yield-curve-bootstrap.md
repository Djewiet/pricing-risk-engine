# ADR 0001 — Yield curve: source, bootstrap and interpolation

- Status: accepted
- Date: 2026-11-11

## Context

Phase 1 needs a discount curve built from free, public market data, reproducible offline,
and validated against an independent implementation.

## Decision

**Source: US Treasury Daily Par Yield Curve Rates.** Official, daily, free, no API key, CSV
download per year, 13–14 tenors from 1 month to 30 years. Alternatives rejected: FRED
(requires an API key and mirrors the same data), ECB yield curves (published as fitted
Svensson parameters and spot rates, not par instruments, so there is nothing to bootstrap).

**Instruments: par bonds.** Each quote is the coupon of a bond issued on the valuation date
and priced at par: semi-annual coupons, ACT/ACT ICMA, unadjusted dates, backward schedule
with a short front stub, settlement on the valuation date.

**Interpolation: log-linear on discount factors, flat-forward extrapolation.** Instantaneous
forwards are piecewise constant between pillars.

**Solver: sequential bootstrap, Brent's method on each pillar's zero rate.**

## Rationale

- Log-linear on discount factors is *local*: a pillar only affects its two adjacent segments.
  The sequential bootstrap is therefore exact in one pass, and bucketed risk (DV01 per pillar)
  does not leak to distant maturities. Positive discount factors and finite forwards are
  guaranteed.
- Cubic splines on zero rates give smooth forwards but are global (a bump at 30Y moves the
  1Y forward) and can produce oscillating or negative forwards. Monotone-convex (Hagan–West)
  is the best of both worlds and the Treasury's own fitting method; it is a candidate for v2.

## Consequences

- Forward rates jump at pillars: acceptable for discounting and vanilla swaps, a limitation
  for products sensitive to the forward curve shape (caps, CMS).
- Quotes up to 1Y are Treasury bills, whose bond-equivalent yield differs slightly from a
  semi-annual par yield. This approximation costs a fraction of a basis point at the short end.
- No business-day calendar: real Treasury cash flows roll to business days. Calendars will be
  added with the bond and swap instruments.
- Validation: discount factors match QuantLib's `PiecewiseLogLinearDiscount` with
  `FixedRateBondHelper` to 1e-11 (QuantLib's solver accuracy) on 5 curve shapes, including
  negative rates, and 6 reference dates chosen to stress end-of-month date generation.
