"""Error tables of the option engines against QuantLib, for the validation report.

Each table row runs the grid of the matching ``validation/test_*`` suite (the grids are
imported, not copied, so the report and the tests always cover the same cases) and records
the *observed* worst error next to the tolerance the test enforces.
"""

import itertools
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
import QuantLib as ql  # noqa: N813 - the conventional alias in QuantLib-Python code

from pricer.analytics import implied_volatility
from pricer.engines import (
    AnalyticEuropeanEngine,
    BinomialTreeEngine,
    monte_carlo_european,
)
from pricer.instruments import AmericanOption, EuropeanOption, OptionType
from pricer.market import FlatForwardCurve, FlatVolatility, MarketSnapshot, YieldCurve
from pricer.models import BlackScholesInputs, BlackScholesModel
from validation import (
    test_american_option_quantlib as american,
)
from validation import (
    test_european_option_quantlib as european,
)
from validation import (
    test_implied_volatility_quantlib as implied,
)
from validation import (
    test_monte_carlo_statistics as statistics,
)
from validation.quantlib_setup import VALUATION, analytic_option, bsm_process, ql_vanilla


@dataclass(frozen=True, slots=True)
class BenchmarkRow:
    """Worst observed error of one quantity over one benchmark grid.

    Attributes:
        suite: What is compared with what.
        quantity: Compared quantity.
        cases: Number of cases in the grid.
        observed: Worst error over the grid, in the unit of ``measure``.
        tolerance: Tolerance enforced by the test suite, same unit.
        measure: How the error is measured.
    """

    suite: str
    quantity: str
    cases: int
    observed: float
    tolerance: float
    measure: str


def _market(spot: float, rates: YieldCurve, dividends: YieldCurve, vol: float) -> MarketSnapshot:
    return MarketSnapshot(
        timestamp=datetime(2025, 11, 12, 21, 0, tzinfo=UTC),
        valuation_date=VALUATION,
        curves={"R": rates, "Q": dividends},
        spots={"X": spot},
        volatilities={"X": FlatVolatility(vol)},
    )


def _flat(rate: float) -> FlatForwardCurve:
    return FlatForwardCurve(VALUATION, rate)


def black_scholes_rows() -> list[BenchmarkRow]:
    """Analytic engine vs ``AnalyticEuropeanEngine``: price and six Greeks."""
    cases: list[tuple[EuropeanOption, float, YieldCurve, YieldCurve, float]] = [
        (EuropeanOption("X", european.STRIKE, e, t), s, _flat(r), _flat(q), v)
        for s, e, r, q, v, t in itertools.product(
            european.SPOTS,
            european.EXPIRIES,
            european.RATES,
            european.DIVIDENDS,
            european.VOLS,
            european.TYPES,
        )
    ]
    cases += [
        (EuropeanOption("X", k, e, t), 100.0, european.TREASURY, _flat(0.015), 0.25)
        for e, k, t in itertools.product(
            european.TERM_STRUCTURE_EXPIRIES, european.TERM_STRUCTURE_STRIKES, european.TYPES
        )
    ]
    worst = dict.fromkeys(("npv", *(name for name, _ in european.GREEKS)), 0.0)
    engine = AnalyticEuropeanEngine(BlackScholesModel("R", "Q"))
    for option, spot, rates, dividends, vol in cases:
        ours = engine.price(option, _market(spot, rates, dividends, vol))
        theirs = analytic_option(option, spot, rates, dividends, vol)
        pairs = [("npv", ours.npv, theirs.NPV())] + [
            (name, getattr(ours.greeks, name), getattr(theirs, ql_name)())
            for name, ql_name in european.GREEKS
        ]
        for name, a, b in pairs:
            worst[name] = max(worst[name], abs(a - b) / max(abs(b), 1.0))
    return [
        BenchmarkRow(
            "Black-Scholes vs QuantLib analytic",
            name,
            len(cases),
            error,
            european.RTOL,
            "max |ours - QL| / max(|QL|, 1)",
        )
        for name, error in worst.items()
    ]


def implied_volatility_rows() -> list[BenchmarkRow]:
    """Implied volatility recovered from QuantLib prices, against the true volatility."""
    worst, count = 0.0, 0
    model = BlackScholesModel("R", "Q")
    for k, e, v, t in itertools.product(
        implied.STRIKES, implied.EXPIRIES, implied.VOLS, implied.TYPES
    ):
        option = EuropeanOption("X", k, e, t)
        rates, dividends = _flat(implied.RATE), _flat(implied.DIVIDEND)
        theirs = analytic_option(option, implied.SPOT, rates, dividends, v)
        sign = t.sign
        intrinsic = max(sign * (implied.SPOT * dividends.discount(e) - k * rates.discount(e)), 0.0)
        if theirs.NPV() - intrinsic < 1e-10 * implied.SPOT or theirs.vega() < 1e-8:
            continue  # time value at noise level: repricing is checked instead (see tests)
        market = _market(implied.SPOT, rates, dividends, v)
        worst = max(worst, abs(implied_volatility(option, theirs.NPV(), model, market) - v))
        count += 1
    return [
        BenchmarkRow(
            "Implied vol from QuantLib prices",
            "volatility",
            count,
            worst,
            implied.VOL_ATOL,
            "max |sigma_implied - sigma_true|",
        )
    ]


def tree_rows() -> list[BenchmarkRow]:
    """CRR tree vs QuantLib's CRR tree (both styles) and vs QuantLib's PDE solver."""
    engine = BinomialTreeEngine(BlackScholesModel("R", "Q"), american.STEPS)
    worst = {"npv": 0.0, "delta": 0.0, "gamma": 0.0, "theta": 0.0}
    count = 0
    for style, (s, e, r, q, v, t) in itertools.product(
        (AmericanOption, EuropeanOption), american.CASES
    ):
        option = style("X", american.STRIKE, e, t)
        ours = engine.price(option, american.market(s, r, q, v))
        theirs = ql_vanilla(option)
        theirs.setPricingEngine(
            ql.BinomialVanillaEngine(bsm_process(s, _flat(r), _flat(q), v), "crr", american.STEPS)
        )
        worst["npv"] = max(worst["npv"], abs(ours.npv - theirs.NPV()))
        worst["delta"] = max(worst["delta"], abs(ours.delta - theirs.delta()))
        worst["gamma"] = max(
            worst["gamma"], abs(ours.gamma - theirs.gamma()) / max(abs(theirs.gamma()), 1e-3)
        )
        payoff = max(t.sign * (s - american.STRIKE), 0.0)
        exercised = option.early_exercise and ours.npv <= payoff + 1e-9
        if not exercised:  # QuantLib's tree theta is undefined there (see the American page)
            worst["theta"] = max(worst["theta"], abs(ours.theta - theirs.theta()))
        count += 1
    suite = f"CRR tree vs QuantLib CRR, N = {american.STEPS}"
    rows = [
        BenchmarkRow(suite, "npv", count, worst["npv"], american.PRICE_TOL, "max abs"),
        BenchmarkRow(suite, "delta", count, worst["delta"], american.DELTA_TOL, "max abs"),
        BenchmarkRow(suite, "gamma", count, worst["gamma"], american.GAMMA_RTOL, "max relative"),
        BenchmarkRow(
            suite, "theta (not exercised)", count, worst["theta"], american.THETA_TOL, "max abs"
        ),
    ]

    fd_worst, fd_count = 0.0, 0
    fd_engine = BinomialTreeEngine(BlackScholesModel("R", "Q"), 2000)
    for s, e, (r, q), t in itertools.product(
        american.SPOTS, american.EXPIRIES[1:], ((0.05, 0.0), (0.01, 0.06)), american.TYPES
    ):
        option = AmericanOption("X", american.STRIKE, e, t)
        ours_npv = fd_engine.price(option, american.market(s, r, q, 0.25)).npv
        theirs = ql_vanilla(option)
        theirs.setPricingEngine(
            ql.FdBlackScholesVanillaEngine(bsm_process(s, _flat(r), _flat(q), 0.25), 800, 800)
        )
        fd_worst = max(fd_worst, abs(ours_npv - theirs.NPV()))
        fd_count += 1
    rows.append(
        BenchmarkRow(
            "American tree N = 2000 vs QuantLib PDE 800 x 800",
            "npv",
            fd_count,
            fd_worst,
            american.FD_TOL,
            "max abs",
        )
    )
    return rows


@dataclass(frozen=True, slots=True)
class CoverageRow:
    """Statistical validation of the Monte Carlo error model for one setting.

    Attributes:
        setting: Variance reduction setting.
        cases: Number of (strike, type) cases.
        coverage_min: Lowest coverage of the 95% interval over the cases.
        coverage_max: Highest coverage of the 95% interval over the cases.
        z_mean_max: Largest ``|mean(z)|`` over the cases.
        z_var_range: Range of ``var(z)`` over the cases.
    """

    setting: str
    cases: int
    coverage_min: float
    coverage_max: float
    z_mean_max: float
    z_var_range: tuple[float, float]


def monte_carlo_coverage_rows() -> list[CoverageRow]:
    """Coverage of the Monte Carlo confidence intervals over many seeds, per setting."""
    inputs = BlackScholesInputs(
        statistics.SPOT,
        1.0,
        float(np.exp(-statistics.RATE)),
        float(np.exp(-statistics.DIVIDEND)),
        statistics.VOL,
    )
    rows = []
    for antithetic, control in itertools.product((False, True), repeat=2):
        coverages, means, variances = [], [], []
        for k, t in itertools.product((80.0, 100.0, 130.0), tuple(OptionType)):
            option = EuropeanOption("X", k, statistics.EXPIRY, t)
            reference = analytic_option(
                option,
                statistics.SPOT,
                _flat(statistics.RATE),
                _flat(statistics.DIVIDEND),
                statistics.VOL,
            ).NPV()
            estimates = [
                monte_carlo_european(
                    option,
                    inputs,
                    statistics.PATHS,
                    np.random.default_rng(seed),
                    antithetic=antithetic,
                    control_variate=control,
                )
                for seed in range(statistics.SEEDS)
            ]
            z = np.array([(v.npv - reference) / v.std_error for v in estimates])
            coverages.append(float(np.mean(np.abs(z) < 1.96)))
            means.append(abs(float(z.mean())))
            variances.append(float(z.var(ddof=1)))
        name = {
            (False, False): "plain",
            (True, False): "antithetic",
            (False, True): "control variate",
            (True, True): "antithetic + control variate",
        }[(antithetic, control)]
        rows.append(
            CoverageRow(
                name,
                len(coverages),
                min(coverages),
                max(coverages),
                max(means),
                (min(variances), max(variances)),
            )
        )
    return rows
