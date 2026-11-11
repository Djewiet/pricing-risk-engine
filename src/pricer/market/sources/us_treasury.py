"""US Treasury daily par yield curve (public, no API key).

The US Treasury publishes every business day the *Daily Treasury Par Yield Curve Rates*:
par yields, on a bond-equivalent (semi-annual) basis, read from a monotone convex spline
fitted to the bid prices of the most recently auctioned securities.
See https://home.treasury.gov/policy-issues/financing-the-government/interest-rate-statistics.

Known approximation: quotes up to 1 year come from Treasury bills (zero-coupon), whose
bond-equivalent yield convention differs slightly from a semi-annual par bond. Treating every
quote as a semi-annual par yield, as done here, is the usual simplification; the error is a
fraction of a basis point on the short end.

Parsing is pure and tested offline; :func:`fetch_par_yields` is a thin network wrapper.
"""

from __future__ import annotations

import csv
import io
import math
import urllib.request
from datetime import date

from pricer.dates.tenor import Tenor, TenorUnit
from pricer.errors import MarketDataError
from pricer.market.bootstrap import ParYieldQuote

CSV_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all"
    "?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
)

#: CSV column header -> tenor. "1.5 Month" (6 weeks) was added in February 2025.
COLUMN_TENORS: dict[str, Tenor] = {
    "1 Mo": Tenor(1, TenorUnit.MONTHS),
    "1.5 Month": Tenor(6, TenorUnit.WEEKS),
    "2 Mo": Tenor(2, TenorUnit.MONTHS),
    "3 Mo": Tenor(3, TenorUnit.MONTHS),
    "4 Mo": Tenor(4, TenorUnit.MONTHS),
    "6 Mo": Tenor(6, TenorUnit.MONTHS),
    "1 Yr": Tenor(1, TenorUnit.YEARS),
    "2 Yr": Tenor(2, TenorUnit.YEARS),
    "3 Yr": Tenor(3, TenorUnit.YEARS),
    "5 Yr": Tenor(5, TenorUnit.YEARS),
    "7 Yr": Tenor(7, TenorUnit.YEARS),
    "10 Yr": Tenor(10, TenorUnit.YEARS),
    "20 Yr": Tenor(20, TenorUnit.YEARS),
    "30 Yr": Tenor(30, TenorUnit.YEARS),
}

_DATE_COLUMN = "Date"


def parse_par_yield_csv(text: str) -> dict[date, tuple[ParYieldQuote, ...]]:
    """Parse the Treasury par yield CSV into quotes by date.

    Rates are converted from percent to decimal. Empty cells (tenors not yet issued, such as
    the 20Y before 2020) are skipped; unknown columns are ignored.

    Raises:
        MarketDataError: If the header has no ``Date`` column or a cell is not a number.
    """
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if reader.fieldnames is None or _DATE_COLUMN not in reader.fieldnames:
        msg = "Treasury CSV has no 'Date' column"
        raise MarketDataError(msg)

    curves: dict[date, tuple[ParYieldQuote, ...]] = {}
    for row in reader:
        as_of = _parse_date(row[_DATE_COLUMN])
        quotes: list[ParYieldQuote] = []
        for column, tenor in COLUMN_TENORS.items():
            cell = (row.get(column) or "").strip()
            if not cell or cell.upper() == "N/A":
                continue
            try:
                percent = float(cell)
            except ValueError:
                msg = f"Invalid {column} rate {cell!r} on {as_of}"
                raise MarketDataError(msg) from None
            if not math.isfinite(percent):
                msg = f"Non-finite {column} rate on {as_of}"
                raise MarketDataError(msg)
            quotes.append(ParYieldQuote(tenor, percent / 100.0))
        curves[as_of] = tuple(quotes)
    return curves


def _parse_date(text: str) -> date:
    """Parse a Treasury ``MM/DD/YYYY`` date."""
    try:
        month, day, year = (int(part) for part in text.split("/"))
        return date(year, month, day)
    except ValueError:
        msg = f"Invalid Treasury date {text!r}, expected MM/DD/YYYY"
        raise MarketDataError(msg) from None


def fetch_par_yields(year: int, timeout: float = 30.0) -> dict[date, tuple[ParYieldQuote, ...]]:
    """Download and parse one calendar year of Treasury par yield curves."""
    request = urllib.request.Request(
        CSV_URL.format(year=year), headers={"User-Agent": "pricing-risk-engine"}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload: bytes = response.read()
    return parse_par_yield_csv(payload.decode("utf-8"))
