"""Assemble the Model Validation Report: compute, plot, write Markdown."""

import platform
from importlib import metadata
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")  # files only, no display

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.figure import Figure

from pricer.engines import binomial_tree, black_scholes
from pricer.instruments import AmericanOption, OptionType
from validation.report.benchmarks import (
    BenchmarkRow,
    CoverageRow,
    black_scholes_rows,
    implied_volatility_rows,
    monte_carlo_coverage_rows,
    tree_rows,
)
from validation.report.convergence import (
    REFERENCE_INPUTS,
    REFERENCE_PUT,
    MonteCarloPoint,
    TreePoint,
    loglog_slope,
    monte_carlo_convergence,
    tree_convergence,
)

DEFAULT_OUTPUT = Path("docs/validation-report")

EVEN_STEPS = (50, 100, 200, 400, 800, 1600, 3200)
ODD_STEPS = tuple(n + 1 for n in EVEN_STEPS)
AMERICAN_STEPS = (50, 100, 200, 400, 800, 1600, 3200, 6400)
MC_PATHS = (1_000, 4_000, 16_000, 64_000, 256_000)
MC_SEEDS = 50
MC_SETTINGS = (
    ("plain", False, False),
    ("antithetic", True, False),
    ("control variate", False, True),
    ("antithetic + control variate", True, True),
)

# Reference categorical palette (validated for colour-vision deficiencies), fixed order.
SERIES = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"


def generate(output: Path) -> Path:
    """Compute every result, write the plots and ``index.md`` into ``output``."""
    output.mkdir(parents=True, exist_ok=True)
    benchmarks = [
        *black_scholes_rows(),
        *implied_volatility_rows(),
        *tree_rows(),
    ]
    coverage = monte_carlo_coverage_rows()

    reference = black_scholes(OptionType.PUT, REFERENCE_PUT.strike, REFERENCE_INPUTS).npv
    even = tree_convergence(REFERENCE_PUT, REFERENCE_INPUTS, EVEN_STEPS, reference)
    odd = tree_convergence(REFERENCE_PUT, REFERENCE_INPUTS, ODD_STEPS, reference)
    american_put = AmericanOption("X", 100.0, REFERENCE_PUT.expiry, OptionType.PUT)
    american = [binomial_tree(american_put, REFERENCE_INPUTS, n).npv for n in AMERICAN_STEPS]
    american_limit = binomial_tree(american_put, REFERENCE_INPUTS, 20_000).npv
    monte_carlo = {
        name: monte_carlo_convergence(
            REFERENCE_PUT,
            REFERENCE_INPUTS,
            MC_PATHS,
            MC_SEEDS,
            antithetic=antithetic,
            control_variate=control,
        )
        for name, antithetic, control in MC_SETTINGS
    }

    _plot_tree(output / "tree-convergence.png", even, odd)
    _plot_american(output / "american-convergence.png", american, american_limit)
    _plot_monte_carlo(output / "monte-carlo-convergence.png", monte_carlo)

    path = output / "index.md"
    path.write_text(
        _markdown(benchmarks, coverage, reference, even, odd, american, american_limit, monte_carlo)
    )
    return path


# --------------------------------------------------------------------------- plots


def _axes(title: str, xlabel: str, ylabel: str) -> tuple[Figure, Axes]:
    fig, ax = plt.subplots(figsize=(7.0, 4.2), dpi=144)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    ax.set_title(title, color=INK, fontsize=11, loc="left")
    ax.set_xlabel(xlabel, color=MUTED, fontsize=9)
    ax.set_ylabel(ylabel, color=MUTED, fontsize=9)
    ax.tick_params(colors=MUTED, labelsize=8)
    ax.grid(True, which="major", color=GRID, linewidth=0.8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    return fig, ax


def _save(fig: Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, facecolor=SURFACE)
    plt.close(fig)


def _plot_tree(path: Path, even: list[TreePoint], odd: list[TreePoint]) -> None:
    fig, ax = _axes(
        "CRR tree: |price error| vs number of steps (ATM 1Y European put)",
        "steps N",
        "|tree - Black-Scholes|",
    )
    for points, label, colour in ((even, "even N", SERIES[0]), (odd, "odd N", SERIES[1])):
        n = [p.steps for p in points]
        ax.loglog(n, [abs(p.error) for p in points], "-o", color=colour, lw=2, ms=5, label=label)
    n0, e0 = even[0].steps, abs(even[0].error)
    ax.loglog(
        [n0, even[-1].steps],
        [e0, e0 * n0 / even[-1].steps],
        "--",
        color=MUTED,
        lw=1,
        label="slope -1",
    )
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    _save(fig, path)


def _plot_american(path: Path, prices: list[float], limit: float) -> None:
    fig, ax = _axes("American put on the CRR tree vs number of steps (ATM, 1Y)", "steps N", "price")
    ax.semilogx(AMERICAN_STEPS, prices, "-o", color=SERIES[0], lw=2, ms=5, label="tree price")
    ax.axhline(limit, color=MUTED, lw=1, ls="--", label=f"N = 20,000: {limit:.4f}")
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    _save(fig, path)


def _plot_monte_carlo(path: Path, results: dict[str, list[MonteCarloPoint]]) -> None:
    fig, ax = _axes(
        f"Monte Carlo: RMSE over {MC_SEEDS} seeds vs paths (ATM 1Y European put)",
        "paths n",
        "RMSE vs Black-Scholes",
    )
    for (name, points), colour in zip(results.items(), SERIES, strict=True):
        n = [p.paths for p in points]
        ax.loglog(n, [p.rmse for p in points], "-o", color=colour, lw=2, ms=5, label=name)
    plain = results["plain"]
    n0, e0 = plain[0].paths, plain[0].rmse
    ax.loglog(
        [n0, plain[-1].paths],
        [e0, e0 * np.sqrt(n0 / plain[-1].paths)],
        "--",
        color=MUTED,
        lw=1,
        label="slope -1/2",
    )
    ax.legend(frameon=False, fontsize=8, labelcolor=INK)
    _save(fig, path)


# --------------------------------------------------------------------------- markdown


def _fmt(x: float) -> str:
    return f"{x:.1e}" if x != 0.0 else "0"


def _markdown(
    benchmarks: list[BenchmarkRow],
    coverage: list[CoverageRow],
    reference: float,
    even: list[TreePoint],
    odd: list[TreePoint],
    american: list[float],
    american_limit: float,
    monte_carlo: dict[str, list[MonteCarloPoint]],
) -> str:
    passed = sum(row.observed <= row.tolerance for row in benchmarks)
    tree_order = loglog_slope([p.steps for p in even], [p.error for p in even])
    lines = [
        "# Model Validation Report",
        "",
        '!!! note "Generated file"',
        "    Produced by `uv run python -m validation.report`; do not edit by hand. Every",
        "    number is recomputed from the code (fixed grids and seeds, deterministic).",
        "",
        "## Scope and methodology",
        "",
        "Models under validation: the Black-Scholes model of an equity underlying and its",
        "three numerical methods (closed form with analytic Greeks, Cox-Ross-Rubinstein",
        "binomial tree for European and American exercise, Monte Carlo with antithetic and",
        "control variates), plus the implied-volatility solver. The rates models of phase 1",
        "(curve bootstrap, bonds, swaps) are validated by the same approach; their QuantLib",
        "results are in [Validation](../validation.md).",
        "",
        "Each method is checked three ways:",
        "",
        "1. **Independent implementation**: QuantLib, configured with the same conventions",
        "   (ACT/365F everywhere, null calendar, flat or bootstrapped curves), on grids that",
        "   cover moneyness, maturity, rates (including negative), dividends and volatility.",
        "2. **Convergence**: numerical methods must converge to the closed form at their",
        "   theoretical rate (tree: $O(1/N)$; Monte Carlo: $O(1/\\sqrt{n})$).",
        "3. **Statistical calibration** (Monte Carlo): the reported standard errors must be",
        "   right, i.e. the 95% confidence intervals must contain the true price 95% of the time.",
        "",
        "Arbitrage and sanity properties (parity, bounds, monotonicity, the Black-Scholes PDE)",
        "are enforced by the unit tests and listed on the [Validation](../validation.md) page.",
        "",
        "## Summary",
        "",
        f"- QuantLib benchmarks: **{passed} of {len(benchmarks)}** quantities within tolerance.",
        f"- CRR tree convergence order: **{tree_order:.3f}** (theory: -1).",
        f"- Monte Carlo standard error order: **{_mc_se_slope(monte_carlo['plain']):.3f}**"
        " (theory: -1/2).",
        f"- Monte Carlo 95% interval coverage: **{min(r.coverage_min for r in coverage):.1%}"
        f" to {max(r.coverage_max for r in coverage):.1%}** over"
        f" {sum(r.cases for r in coverage)} cases x 400 seeds.",
        "",
        "## Benchmarks against QuantLib",
        "",
        "| Comparison | Quantity | Cases | Worst observed | Tolerance | Measure |",
        "|---|---|---:|---:|---:|---|",
    ]
    lines += [
        f"| {r.suite} | {r.quantity} | {r.cases} | {_fmt(r.observed)} | {_fmt(r.tolerance)} "
        f"| {r.measure.replace('|', '\\|')} |"
        for r in benchmarks
    ]
    lines += [
        "",
        "The closed form and the implied volatility agree with QuantLib to rounding. The",
        "tree gap is *expected*: QuantLib's CRR uses a first-order expansion of our up",
        "probability, so the two trees differ by $O(1/N)$; their agreement with the closed",
        "form (below) and with a PDE solver is what validates the tree. Where an American",
        "option is exercised immediately, QuantLib's tree theta (derived from the PDE) is",
        "not comparable and is excluded; see",
        "[American options](../finance/american-options.md#greeks-from-the-tree).",
        "",
        "## Monte Carlo error model",
        "",
        "For each setting: 6 cases (strikes 80, 100, 130 x call, put), 400 seeds x 2,000",
        "paths each, against QuantLib's closed form. $z = (\\hat V - V)/\\text{s.e.}$ should be",
        "standard normal.",
        "",
        "| Setting | 95% coverage (min - max) | max abs mean(z) | var(z) (min - max) |",
        "|---|---:|---:|---:|",
    ]
    lines += [
        f"| {r.setting} | {r.coverage_min:.1%} - {r.coverage_max:.1%} | {r.z_mean_max:.3f} "
        f"| {r.z_var_range[0]:.2f} - {r.z_var_range[1]:.2f} |"
        for r in coverage
    ]
    lines += [
        "",
        "Accepted bands (3 sampling standard deviations for 400 seeds): coverage 91.7% to",
        "98.3%, mean within 0.2, variance 0.75 to 1.3.",
        "",
        "## Convergence of the binomial tree",
        "",
        f"Reference: one-year at-the-money European put, $S = K = 100$, $r = 5\\%$,"
        f" $q = 2\\%$, $\\sigma = 25\\%$; Black-Scholes price {reference:.6f}.",
        "",
        "![CRR tree convergence](tree-convergence.png)",
        "",
        "| N (even) | error | N (odd) | error | error x N (even) |",
        "|---:|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {e.steps} | {e.error:+.2e} | {o.steps} | {o.error:+.2e} | {e.error * e.steps:+.3f} |"
        for e, o in zip(even, odd, strict=True)
    ]
    lines += [
        "",
        "The error is $O(1/N)$ (error x N is constant) and **changes sign with the parity of**",
        "$N$: even trees have a node at the strike, odd trees straddle it. Averaging $N$ and",
        "$N + 1$, or smoothing the last step with Black-Scholes, removes most of it.",
        "",
        "### American put",
        "",
        "![American put convergence](american-convergence.png)",
        "",
        "| N | price | minus N = 20,000 |",
        "|---:|---:|---:|",
    ]
    lines += [
        f"| {n} | {p:.6f} | {p - american_limit:+.2e} |"
        for n, p in zip(AMERICAN_STEPS, american, strict=True)
    ]
    lines += [
        "",
        f"The European price of the same put is {reference:.6f}: the early exercise premium is"
        f" about {american_limit - reference:.4f}.",
        "",
        "## Convergence of Monte Carlo",
        "",
        f"Same European put; root mean square error over {MC_SEEDS} seeds, and the average",
        "reported standard error.",
        "",
        "![Monte Carlo convergence](monte-carlo-convergence.png)",
        "",
        "| Setting | " + " | ".join(f"n = {n:,}" for n in MC_PATHS) + " | RMSE order |",
        "|---|" + "---:|" * (len(MC_PATHS) + 1),
    ]
    for name, points in monte_carlo.items():
        cells = " | ".join(f"{p.rmse:.1e} ({p.mean_std_error:.1e})" for p in points)
        slope = loglog_slope([p.paths for p in points], [p.rmse for p in points])
        lines.append(f"| {name} | {cells} | {slope:.2f} |")
    plain_var = monte_carlo["plain"][-1].mean_std_error ** 2
    lines += [
        "",
        "Cells: RMSE (average reported standard error). The RMSE order is noisy with 50",
        "seeds; the standard-error order is exact up to sampling: "
        + ", ".join(f"{name} {_mc_se_slope(points):.3f}" for name, points in monte_carlo.items())
        + ".",
        "",
        "Variance reduction at n = 256,000, as a ratio of variances (equivalent path"
        " multiplier): "
        + ", ".join(
            f"{name} x{plain_var / points[-1].mean_std_error ** 2:.1f}"
            for name, points in monte_carlo.items()
            if name != "plain"
        )
        + ". The control variate gains much more deep in the money, where the payoff is"
        " almost linear in the spot (see [Monte Carlo pricing](../finance/monte-carlo.md)).",
        "",
        "## Known limitations",
        "",
        "- **Lognormal dynamics with deterministic rates and volatility.** No smile dynamics,",
        "  no jumps, no stochastic rates; the engines read $\\sigma(T, K)$ from a surface but",
        "  the Greeks assume the surface does not move with the spot. Heston comes in phase 3.",
        "- **Continuous dividend yield.** Discrete cash dividends are not modelled; this",
        "  matters most for American calls on single stocks.",
        "- **Tree rates are the zero rates to expiry.** Exact for European options; for",
        "  American options under a sloped curve the exercise decision uses a flat rate.",
        "- **CRR oscillation.** First-order convergence with parity effects; no smoothing,",
        "  Richardson extrapolation or Leisen-Reimer tree yet.",
        "- **Monte Carlo is European only.** American exercise by simulation (Longstaff-",
        "  Schwartz) and path-dependent payoffs are out of scope; gamma by bump is noisy",
        "  (no pathwise or likelihood-ratio estimators).",
        "- **Implied volatility** is limited by vega: far from the money at low volatility",
        "  the time value is below double precision and no volatility can be implied.",
        "- **Theta conventions** differ between the analytic Greeks (zero rates to expiry",
        "  fixed) and the bump (forwards realised); both are documented.",
        "",
        "## Environment",
        "",
        f"Python {platform.python_version()}, NumPy {np.__version__}, QuantLib"
        f" {metadata.version('QuantLib')}, matplotlib {mpl.__version__}.",
        "",
    ]
    return "\n".join(lines)


def _mc_se_slope(points: list[MonteCarloPoint]) -> float:
    return loglog_slope([p.paths for p in points], [p.mean_std_error for p in points])
