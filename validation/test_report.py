"""The Model Validation Report generates end to end, with every benchmark in tolerance."""

import re
from pathlib import Path

import pytest

pytest.importorskip("QuantLib")
pytest.importorskip("matplotlib")

from validation.report import generate

SECTIONS = (
    "## Scope and methodology",
    "## Summary",
    "## Benchmarks against QuantLib",
    "## Monte Carlo error model",
    "## Convergence of the binomial tree",
    "## Convergence of Monte Carlo",
    "## Known limitations",
    "## Environment",
)
PLOTS = ("tree-convergence.png", "american-convergence.png", "monte-carlo-convergence.png")


def test_report_is_generated(tmp_path: Path) -> None:
    """``generate`` writes ``index.md`` with every section, the plots and no failure."""
    path = generate(tmp_path)
    text = path.read_text()
    assert path == tmp_path / "index.md"
    for section in SECTIONS:
        assert section in text
    for plot in PLOTS:
        assert (tmp_path / plot).stat().st_size > 10_000
        assert f"]({plot})" in text

    passed = re.search(r"QuantLib benchmarks: \*\*(\d+) of (\d+)\*\*", text)
    assert passed is not None
    assert passed.group(1) == passed.group(2)  # every benchmark within its tolerance
