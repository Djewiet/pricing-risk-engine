"""Vanilla equity options."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import ClassVar

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]


class OptionType(Enum):
    """Call or put."""

    CALL = "call"
    PUT = "put"

    @property
    def sign(self) -> int:
        """``+1`` for a call, ``-1`` for a put.

        Written ``omega`` in the formulas: the payoff is ``max(omega * (S - K), 0)`` and the
        Black-Scholes price is ``omega * (S Dq N(omega d1) - K Dr N(omega d2))``, so one code
        path serves both types.
        """
        return 1 if self is OptionType.CALL else -1


@dataclass(frozen=True, slots=True)
class VanillaOption:
    """Call or put on one unit of an underlying: the terms shared by every exercise style.

    Not instantiated directly: use :class:`EuropeanOption` or :class:`AmericanOption`. The
    exercise style is a contract term exposed as :attr:`early_exercise`, so a numerical
    method that handles both styles (a tree) reads the term instead of testing the class.

    The instrument holds contract terms only. Its value depends on a model of the
    underlying and on market data, so it lives in an engine. The payoff is paid on the
    exercise date (no settlement lag) and the option is cash-settled: physical delivery
    has the same value under the models of this library.

    Attributes:
        underlying: Identifier of the underlying in the market snapshot (spot, volatility).
        strike: Strike price, in the currency of the underlying.
        expiry: Last exercise date.
        option_type: Call or put.
    """

    early_exercise: ClassVar[bool]

    underlying: str
    strike: float
    expiry: date
    option_type: OptionType

    def __post_init__(self) -> None:
        if type(self) is VanillaOption:
            msg = "VanillaOption is abstract: use EuropeanOption or AmericanOption"
            raise TypeError(msg)
        if not (math.isfinite(self.strike) and self.strike > 0.0):
            msg = f"Strike must be finite and positive, got {self.strike}"
            raise ValueError(msg)

    def payoff(self, spot: FloatArray) -> FloatArray:
        """Exercise value ``max(omega (S - K), 0)``, vectorised over spots."""
        omega = self.option_type.sign
        return np.maximum(omega * (spot - self.strike), 0.0)

    def is_expired(self, valuation_date: date) -> bool:
        """Whether the option has been exercised or has lapsed before ``valuation_date``.

        An option expiring on the valuation date is still alive: it is worth its payoff.
        """
        return self.expiry < valuation_date


@dataclass(frozen=True, slots=True)
class EuropeanOption(VanillaOption):
    """Option exercisable on its expiry date only.

    Priced in closed form by :mod:`pricer.engines.analytic_european`, or by a tree.
    """

    early_exercise: ClassVar[bool] = False


@dataclass(frozen=True, slots=True)
class AmericanOption(VanillaOption):
    """Option exercisable on any day up to and including its expiry date.

    The holder exercises when the payoff exceeds the value of keeping the option alive, so
    an American option is worth at least its European twin and at least its payoff. No
    closed form exists for a put (or a call on a dividend-paying underlying): it is priced
    by a tree (:mod:`pricer.engines.binomial`).
    """

    early_exercise: ClassVar[bool] = True
