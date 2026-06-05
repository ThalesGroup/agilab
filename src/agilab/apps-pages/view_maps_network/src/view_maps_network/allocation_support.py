from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

def safe_literal_eval(value):
    try:
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value

_ALLOC_STEP_CANDIDATES = ("time_index", "decision", "step", "time_idx")
_ALLOC_TIME_CANDIDATES = ("time_s", "t_now_s", "time", "t")


def _pick_ci_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> Optional[str]:
    if df.empty:
        return None
    lower_map = {str(c).lower(): str(c) for c in df.columns}
    for key in candidates:
        col = lower_map.get(key.lower())
        if col is not None:
            return col
    return None


def _parse_allocations_cell(value: Any) -> list[dict[str, Any]]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    parsed: Any = value
    if isinstance(parsed, str):
        parsed = safe_literal_eval(parsed)
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, tuple):
        parsed = list(parsed)
    if not isinstance(parsed, list):
        return []
    rows: list[dict[str, Any]] = []
    for item in parsed:
        obj = safe_literal_eval(item) if isinstance(item, str) else item
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _coerce_alloc_time_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    normalized = df.copy()
    step_col = _pick_ci_column(normalized, _ALLOC_STEP_CANDIDATES)
    if "time_index" not in normalized.columns and step_col is not None:
        normalized["time_index"] = normalized[step_col]
    if "time_index" not in normalized.columns:
        normalized["time_index"] = 0

    step_num = pd.to_numeric(normalized["time_index"], errors="coerce")
    if step_num.notna().any():
        if step_num.isna().any():
            fallback = pd.Series(np.arange(len(normalized), dtype=float), index=normalized.index)
            step_num = step_num.combine_first(fallback)
        normalized["time_index"] = step_num.round().astype("Int64")
    else:
        normalized["time_index"] = pd.Series(np.arange(len(normalized)), index=normalized.index, dtype="Int64")
    return normalized


def _drop_index_levels_shadowing_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Drop named index levels that duplicate real column labels."""
    if df.empty:
        return df
    index_names = [name for name in df.index.names if name is not None]
    duplicated = [name for name in index_names if name in df.columns]
    if not duplicated:
        return df
    return df.reset_index(level=duplicated, drop=True)


def _normalize_allocations_frame(df_in: pd.DataFrame) -> pd.DataFrame:
    if df_in.empty:
        return df_in
    df = df_in.copy()

    src_col = _pick_ci_column(df, ("source", "src", "from"))
    dst_col = _pick_ci_column(df, ("destination", "dst", "dest", "to", "target"))
    if src_col is not None and src_col != "source":
        df["source"] = df[src_col]
    if dst_col is not None and dst_col != "destination":
        df["destination"] = df[dst_col]

    alloc_col = _pick_ci_column(df, ("allocations",))
    if alloc_col is not None and ("source" not in df.columns or "destination" not in df.columns):
        step_col = _pick_ci_column(df, _ALLOC_STEP_CANDIDATES)
        t_col = _pick_ci_column(df, _ALLOC_TIME_CANDIDATES)
        rows: list[dict[str, Any]] = []
        for idx, row in df.iterrows():
            step_value = row.get(step_col) if step_col is not None else idx
            t_value = row.get(t_col) if t_col is not None else None
            for alloc in _parse_allocations_cell(row.get(alloc_col)):
                merged = dict(alloc)
                merged.setdefault("time_index", step_value)
                if t_value is not None:
                    merged.setdefault("time_s", t_value)
                    merged.setdefault("t_now_s", t_value)
                rows.append(merged)
        if rows:
            df = pd.DataFrame(rows)

    df = _coerce_alloc_time_index(df)

    t_col = _pick_ci_column(df, _ALLOC_TIME_CANDIDATES)
    if t_col is not None:
        t_num = pd.to_numeric(df[t_col], errors="coerce")
        if t_num.notna().any():
            df["time_s"] = t_num
            if "t_now_s" not in df.columns:
                df["t_now_s"] = t_num
    return df


def load_allocations(path: Path) -> pd.DataFrame:
    path = path.expanduser()
    if not path.exists():
        return pd.DataFrame()
    if path.suffix.lower() == ".csv":
        try:
            return _normalize_allocations_frame(pd.read_csv(path))
        except Exception:
            return pd.DataFrame()
    if path.suffix.lower() in {".parquet", ".pq", ".parq"}:
        try:
            return _normalize_allocations_frame(pd.read_parquet(path))
        except Exception:
            return pd.DataFrame()
    try:
        if path.suffix.lower() in {".jsonl", ".ndjson"}:
            records: list[Any] = []
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
            data: Any = records
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return _normalize_allocations_frame(pd.DataFrame(data))
        elif isinstance(data, dict):
            return _normalize_allocations_frame(pd.DataFrame([data]))
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()

def _nearest_row(df: pd.DataFrame, t: float, time_col: str = "time_s") -> pd.DataFrame:
    if df.empty or time_col not in df.columns:
        return df
    series = pd.to_numeric(df[time_col], errors="coerce")
    if series.dropna().empty:
        return df.iloc[0:0]
    idx = (series - t).abs().idxmin()
    return df.loc[[idx]]
