import io
import urllib.request
from datetime import date
from types import TracebackType
from typing import Self

import pytest

from pricer.dates import Tenor
from pricer.errors import MarketDataError
from pricer.market import bootstrap_par_yield_curve, par_yield
from pricer.market.sources.us_treasury import fetch_par_yields, parse_par_yield_csv

# SYNTHETIC data in the exact layout of the Treasury CSV (header, newest date first,
# BOM, empty cells). Values are illustrative, not historical quotes.
SAMPLE_CSV = (
    "﻿Date,1 Mo,1.5 Month,2 Mo,3 Mo,4 Mo,6 Mo,1 Yr,2 Yr,3 Yr,5 Yr,7 Yr,10 Yr,20 Yr,30 Yr\n"
    "08/29/2025,4.40,4.38,4.35,4.30,4.20,4.05,3.85,3.60,3.55,3.65,3.85,4.20,4.80,4.90\n"
    "08/28/2025,4.41,,4.36,4.31,4.21,4.06,3.86,3.61,3.56,3.66,3.86,4.21,4.81,N/A\n"
)


def test_parse_converts_percent_and_skips_empty_cells() -> None:
    curves = parse_par_yield_csv(SAMPLE_CSV)
    assert set(curves) == {date(2025, 8, 29), date(2025, 8, 28)}
    full = curves[date(2025, 8, 29)]
    assert len(full) == 14
    assert full[0].tenor == Tenor.parse("1M")
    assert full[0].rate == pytest.approx(0.044)
    assert full[1].tenor == Tenor.parse("6W")
    assert len(curves[date(2025, 8, 28)]) == 12


def test_parsed_curve_bootstraps() -> None:
    quotes = parse_par_yield_csv(SAMPLE_CSV)[date(2025, 8, 29)]
    curve = bootstrap_par_yield_curve(date(2025, 8, 29), quotes)
    for q in quotes:
        maturity = q.tenor.advance(date(2025, 8, 29))
        assert par_yield(curve, maturity) == pytest.approx(q.rate, abs=1e-12)


def test_unknown_columns_are_ignored() -> None:
    curves = parse_par_yield_csv("Date,1 Mo,Foo\n01/02/2025,4.4,abc\n")
    assert len(curves[date(2025, 1, 2)]) == 1


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("Day,1 Mo\n01/02/2025,4.4\n", "no 'Date' column"),
        ("", "no 'Date' column"),
        ("Date,1 Mo\n01/02/2025,abc\n", "Invalid 1 Mo rate"),
        ("Date,1 Mo\n01/02/2025,inf\n", "Non-finite"),
        ("Date,1 Mo\n2025-01-02,4.4\n", "Invalid Treasury date"),
        ("Date,1 Mo\n02/30/2025,4.4\n", "Invalid Treasury date"),
    ],
)
def test_parse_errors(text: str, match: str) -> None:
    with pytest.raises(MarketDataError, match=match):
        parse_par_yield_csv(text)


class _FakeResponse(io.BytesIO):
    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def test_fetch_builds_year_url_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: float) -> _FakeResponse:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        return _FakeResponse(SAMPLE_CSV.encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    curves = fetch_par_yields(2025, timeout=5.0)
    assert date(2025, 8, 29) in curves
    assert "daily-treasury-rates.csv/2025/all" in str(seen["url"])
    assert "field_tdr_date_value=2025" in str(seen["url"])
    assert seen["timeout"] == 5.0
