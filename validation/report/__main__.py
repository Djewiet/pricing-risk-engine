"""Command line entry point: ``uv run python -m validation.report [--output DIR]``."""

import argparse
from pathlib import Path

from validation.report.generate import DEFAULT_OUTPUT, generate


def main() -> None:
    """Generate the report and print where it was written."""
    parser = argparse.ArgumentParser(description="Generate the Model Validation Report.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output directory (default: {DEFAULT_OUTPUT})",
    )
    path = generate(parser.parse_args().output)
    print(f"Model Validation Report written to {path}")


if __name__ == "__main__":
    main()
