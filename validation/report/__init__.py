"""Model Validation Report generator.

``uv run python -m validation.report`` recomputes every number of the report (QuantLib
benchmarks, Monte Carlo coverage, convergence studies) and writes it as Markdown with PNG
plots, by default into ``docs/validation-report/`` where MkDocs publishes it. Everything is
deterministic (fixed grids, fixed seeds), so regenerating the report on the same versions
gives the same numbers.
"""

from validation.report.generate import generate

__all__ = ["generate"]
