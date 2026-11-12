"""Discounting engine for fixed-rate bonds."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from pricer.errors import PricerError
from pricer.instruments.bond import FixedRateBond
from pricer.market.curves import YieldCurve
from pricer.market.snapshot import MarketSnapshot


@dataclass(frozen=True, slots=True)
class BondValuation:
    """Valuation of a bond at its settlement date.

    Prices are quoted per 100 of face amount, as on the market.

    Attributes:
        settlement_date: Date the price applies to.
        npv: Present value in currency (the dirty price applied to the face amount).
        dirty_price: Full price per 100 of face, including accrued interest.
        clean_price: Quoted price per 100 of face: dirty price minus accrued interest.
        accrued_interest: Accrued interest per 100 of face.
    """

    settlement_date: date
    npv: float
    dirty_price: float
    clean_price: float
    accrued_interest: float


def discount_bond(bond: FixedRateBond, curve: YieldCurve) -> BondValuation:
    """Value a bond by discounting its remaining cash flows on ``curve``.

    ``PV = sum_i CF_i * P(0, t_i)`` over the flows paid after the curve reference date,
    which is also the settlement date (T+0 settlement).

    Raises:
        PricerError: If the bond has no cash flow left after the settlement date.
    """
    settlement = curve.reference_date
    flows = bond.remaining_cashflows(settlement)
    if not flows:
        msg = f"Bond maturing on {bond.maturity} has no cash flow after {settlement}"
        raise PricerError(msg)
    times = np.array([curve.time(cf.payment_date) for cf in flows], dtype=np.float64)
    amounts = np.array([cf.amount for cf in flows], dtype=np.float64)
    npv = float(np.dot(amounts, curve.discount_factors(times)))
    dirty = 100.0 * npv / bond.face_amount
    accrued = bond.accrued_interest(settlement)
    return BondValuation(settlement, npv, dirty, dirty - accrued, accrued)


@dataclass(frozen=True, slots=True)
class DiscountingBondEngine:
    """Values bonds by discounting their cash flows on one curve of the snapshot.

    Attributes:
        curve_name: Identifier of the discount curve in the market snapshot.
    """

    curve_name: str

    def price(self, instrument: FixedRateBond, market: MarketSnapshot, /) -> BondValuation:
        """Value ``instrument`` on the engine curve of ``market``."""
        return discount_bond(instrument, market.curve(self.curve_name))
