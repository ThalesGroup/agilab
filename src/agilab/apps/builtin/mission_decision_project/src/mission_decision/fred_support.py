"""Optional FRED public-data helpers for the Mission Decision demo.

The default demo stays offline and deterministic. Live FRED access is kept as a
thin optional CSV fetch path so the app does not add a dependency on ``fredapi``
or require API credentials for first-run validation.
"""

from __future__ import annotations

import csv
from io import StringIO
from typing import Any, Callable
from urllib.parse import quote
from urllib.request import urlopen


FRED_CSV_BASE_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"
FRED_FIXTURE_SERIES_ID = "FEDFUNDS"
FRED_FIXTURE_SERIES_NAME = "Effective Federal Funds Rate"
FRED_FIXTURE_CSV = """DATE,FEDFUNDS
2026-01-01,4.00
2026-02-01,3.95
2026-03-01,3.90
"""


def fred_csv_url(series_id: str = FRED_FIXTURE_SERIES_ID) -> str:
    """Return the public FRED CSV endpoint for a series."""

    normalized = series_id.strip().upper()
    if not normalized:
        raise ValueError("FRED series id must not be empty")
    return f"{FRED_CSV_BASE_URL}?id={quote(normalized)}"


def parse_fred_csv(text: str, *, series_id: str = FRED_FIXTURE_SERIES_ID) -> list[dict[str, Any]]:
    """Parse FRED CSV text into typed observation rows."""

    normalized = series_id.strip().upper()
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames or "DATE" not in reader.fieldnames or normalized not in reader.fieldnames:
        raise ValueError(f"FRED CSV must contain DATE and {normalized} columns")

    rows: list[dict[str, Any]] = []
    for raw in reader:
        raw_date = str(raw.get("DATE", "")).strip()
        raw_value = str(raw.get(normalized, "")).strip()
        if not raw_date or raw_value in {"", "."}:
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        rows.append(
            {
                "date": raw_date,
                "series_id": normalized,
                "value": value,
                "source": "fred",
            }
        )
    return rows


def fred_fixture_rows() -> list[dict[str, Any]]:
    """Return a deterministic FRED-shaped fixture used by public demos/tests."""

    rows = parse_fred_csv(FRED_FIXTURE_CSV, series_id=FRED_FIXTURE_SERIES_ID)
    for row in rows:
        row["source"] = "fred_fixture"
    return rows


def fred_fixture_feature_rows() -> list[dict[str, Any]]:
    """Return feature-table rows describing the bundled FRED context fixture."""

    rows = fred_fixture_rows()
    if not rows:
        return []
    fixture_row = rows[-1]
    return [
        {
            "feature": "public_macro_fixture_series",
            "value": FRED_FIXTURE_SERIES_ID,
            "unit": "fred_series",
            "source": "fred_fixture",
        },
        {
            "feature": "public_macro_fixture_value",
            "value": fixture_row["value"],
            "unit": "percent",
            "source": "fred_fixture",
        },
        {
            "feature": "public_macro_fixture_date",
            "value": fixture_row["date"],
            "unit": "date",
            "source": "fred_fixture",
        },
    ]


def fetch_fred_csv_rows(
    series_id: str = FRED_FIXTURE_SERIES_ID,
    *,
    opener: Callable[..., Any] = urlopen,
    timeout: float = 10.0,
) -> list[dict[str, Any]]:
    """Fetch and parse live public FRED CSV data.

    This function is intentionally not used by the default app path. It exists so
    custom demos can opt in to live public data without changing AGILAB's first
    run behavior.
    """

    with opener(fred_csv_url(series_id), timeout=timeout) as response:
        payload = response.read().decode("utf-8")
    return parse_fred_csv(payload, series_id=series_id)


__all__ = [
    "FRED_CSV_BASE_URL",
    "FRED_FIXTURE_CSV",
    "FRED_FIXTURE_SERIES_ID",
    "FRED_FIXTURE_SERIES_NAME",
    "fetch_fred_csv_rows",
    "fred_csv_url",
    "fred_fixture_feature_rows",
    "fred_fixture_rows",
    "parse_fred_csv",
]
