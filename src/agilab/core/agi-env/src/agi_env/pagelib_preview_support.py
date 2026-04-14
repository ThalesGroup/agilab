from __future__ import annotations

import os
from pathlib import Path

import pandas as pd


def resolve_preview_nrows(explicit_nrows: object, session_max_rows: object) -> int | None:
    raw_value = session_max_rows if explicit_nrows is None else explicit_nrows
    if raw_value is None:
        return None
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return None
    return None if value == 0 else value


def build_dataframe_preview(
    df: pd.DataFrame,
    *,
    max_rows: int,
    max_cols: int,
    truncation_label: str | None = None,
) -> tuple[pd.DataFrame, str | None]:
    if not isinstance(df, pd.DataFrame):
        raise TypeError("render_dataframe_preview expects a pandas DataFrame")

    row_count, col_count = df.shape
    preview = df.iloc[:max_rows, :max_cols]

    truncated_rows = row_count > max_rows
    truncated_cols = col_count > max_cols
    if not (truncated_rows or truncated_cols):
        return preview, None

    label = truncation_label or "Preview truncated"
    details: list[str] = []
    if truncated_rows:
        details.append(f"showing first {min(row_count, max_rows):,} of {row_count:,} rows")
    if truncated_cols:
        details.append(f"showing first {min(col_count, max_cols):,} of {col_count:,} columns")
    return preview, f"{label}: " + ", ".join(details) + "."


def resolve_export_target(path_like: str | Path) -> tuple[Path | None, str | None]:
    path_str = str(path_like).strip()
    if not path_str:
        return None, "Please provide a filename for the export."

    expanded_path = os.path.expanduser(os.path.expandvars(path_str))
    path = Path(expanded_path)
    if path.is_dir():
        return None, f"{path} is a directory instead of a filename."

    return path, None
