"""Option sensitivities (Greeks) and their units."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Greeks:
    """First- and second-order sensitivities of an option value.

    Every Greek is a plain partial derivative, per unit of the risk factor, as in QuantLib.
    Market quoting units are a rescaling: vega per vol point is ``vega / 100``, rho per
    basis point is ``rho / 10_000``, theta per calendar day is ``theta / 365``.

    Attributes:
        delta: ``dV/dS``.
        gamma: ``d2V/dS2``.
        vega: ``dV/dsigma``, per unit of volatility (1.00 = 100 vol points).
        theta: ``dV/dt``, per year, as calendar time passes with the spot, the zero rates
            ``r``, ``q`` to expiry and the volatility held fixed. Usually negative for a
            long option: time decay.
        rho: ``dV/dr``, per unit of the continuously-compounded risk-free zero rate to
            expiry.
        dividend_rho: ``dV/dq``, per unit of the continuously-compounded dividend yield.
    """

    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float
    dividend_rho: float

    @property
    def theta_per_day(self) -> float:
        """Value lost or gained over one calendar day, ``theta / 365``."""
        return self.theta / 365.0
