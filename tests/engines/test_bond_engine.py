import math
from datetime import UTC, date, datetime

import pytest

from pricer.dates import Tenor
from pricer.engines import BondValuation, DiscountingBondEngine, PricingEngine, discount_bond
from pricer.errors import MissingMarketDataError, PricerError
from pricer.instruments import FixedRateBond
from pricer.market import (
    FlatForwardCurve,
    MarketSnapshot,
    ParYieldQuote,
    bootstrap_par_yield_curve,
)

REF = date(2025, 8, 29)
RATES = {"6M": 0.0405, "1Y": 0.0385, "2Y": 0.036, "5Y": 0.0365, "10Y": 0.042, "30Y": 0.049}
CURVE = bootstrap_par_yield_curve(REF, [ParYieldQuote(Tenor.parse(k), v) for k, v in RATES.items()])


@pytest.mark.parametrize(("tenor", "rate"), RATES.items())
def test_par_bonds_price_at_par_on_their_own_curve(tenor: str, rate: float) -> None:
    # The bootstrap and the engine are independent pieces of code: this closes the loop.
    bond = FixedRateBond(REF, Tenor.parse(tenor).advance(REF), rate)
    valuation = discount_bond(bond, CURVE)
    assert valuation.dirty_price == pytest.approx(100.0, abs=1e-10)
    assert valuation.clean_price == pytest.approx(100.0, abs=1e-10)
    assert valuation.accrued_interest == 0.0


def test_flat_curve_closed_form() -> None:
    curve = FlatForwardCurve(REF, 0.03)
    bond = FixedRateBond(date(2024, 2, 29), date(2028, 2, 29), 0.045, face_amount=1_000.0)
    expected = sum(
        cf.amount * math.exp(-0.03 * (cf.payment_date - REF).days / 365)
        for cf in bond.remaining_cashflows(REF)
    )
    valuation = discount_bond(bond, curve)
    assert valuation.npv == pytest.approx(expected, rel=1e-14)
    assert valuation.dirty_price == pytest.approx(expected / 10, rel=1e-14)
    assert valuation.clean_price == pytest.approx(
        valuation.dirty_price - bond.accrued_interest(REF)
    )
    assert valuation.settlement_date == REF


def test_dirty_price_is_continuous_across_coupon_date_minus_coupon() -> None:
    # On the coupon date the coupon leaves the dirty price and accrued resets to zero:
    # clean prices on both sides of the coupon date stay close.
    bond = FixedRateBond(date(2024, 8, 31), date(2030, 8, 31), 0.05)
    before = discount_bond(bond, FlatForwardCurve(date(2026, 2, 27), 0.04))
    on = discount_bond(bond, FlatForwardCurve(date(2026, 2, 28), 0.04))
    assert before.dirty_price - on.dirty_price == pytest.approx(2.5, abs=0.02)
    assert before.clean_price == pytest.approx(on.clean_price, abs=0.02)


def test_matured_bond_raises() -> None:
    bond = FixedRateBond(date(2020, 1, 1), REF, 0.05)
    with pytest.raises(PricerError, match="no cash flow"):
        discount_bond(bond, CURVE)


def test_engine_reads_its_curve_from_the_snapshot() -> None:
    market = MarketSnapshot(datetime(2025, 8, 29, 21, tzinfo=UTC), REF, curves={"UST": CURVE})
    engine: PricingEngine[FixedRateBond, BondValuation] = DiscountingBondEngine("UST")
    bond = FixedRateBond(REF, date(2030, 8, 29), 0.0365)
    assert engine.price(bond, market) == discount_bond(bond, CURVE)
    with pytest.raises(MissingMarketDataError):
        DiscountingBondEngine("EUR").price(bond, market)
