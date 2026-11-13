import math
from datetime import date

import numpy as np
import pytest

from pricer.instruments import AmericanOption, EuropeanOption, OptionType, VanillaOption

EXPIRY = date(2026, 6, 19)


def test_sign() -> None:
    assert OptionType.CALL.sign == 1
    assert OptionType.PUT.sign == -1


def test_payoff_is_vectorised() -> None:
    spots = np.array([80.0, 100.0, 120.0])
    call = EuropeanOption("X", 100.0, EXPIRY, OptionType.CALL)
    put = EuropeanOption("X", 100.0, EXPIRY, OptionType.PUT)
    np.testing.assert_array_equal(call.payoff(spots), [0.0, 0.0, 20.0])
    np.testing.assert_array_equal(put.payoff(spots), [20.0, 0.0, 0.0])
    # Static replication of a forward: call - put = S - K.
    np.testing.assert_array_equal(call.payoff(spots) - put.payoff(spots), spots - 100.0)


@pytest.mark.parametrize("strike", [0.0, -1.0, math.inf, math.nan])
def test_rejects_invalid_strike(strike: float) -> None:
    with pytest.raises(ValueError, match="Strike"):
        EuropeanOption("X", strike, EXPIRY, OptionType.CALL)


def test_alive_on_expiry_date() -> None:
    option = EuropeanOption("X", 100.0, EXPIRY, OptionType.CALL)
    assert not option.is_expired(EXPIRY)
    assert option.is_expired(date(2026, 6, 20))


def test_exercise_style_is_a_contract_term() -> None:
    european = EuropeanOption("X", 100.0, EXPIRY, OptionType.PUT)
    american = AmericanOption("X", 100.0, EXPIRY, OptionType.PUT)
    assert not european.early_exercise
    assert american.early_exercise
    assert european != american  # type: ignore[comparison-overlap]  # different contracts
    np.testing.assert_array_equal(american.payoff(np.array([90.0])), [10.0])


def test_vanilla_option_is_abstract() -> None:
    with pytest.raises(TypeError, match="abstract"):
        VanillaOption("X", 100.0, EXPIRY, OptionType.CALL)
    with pytest.raises(ValueError, match="Strike"):
        AmericanOption("X", -1.0, EXPIRY, OptionType.CALL)
