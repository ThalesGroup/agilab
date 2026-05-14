# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
import ast
import fnmatch
import html
import json
import sys
import tomllib
from pathlib import Path
from typing import Any, Sequence

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st


def _ensure_repo_on_path() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "agilab"
        if candidate.is_dir():
            src_root = candidate.parent
            repo_root = src_root.parent
            for entry in (str(src_root), str(repo_root)):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            break


_ensure_repo_on_path()

from agi_env import AgiEnv
from agi_gui.pagelib import render_logo


PAGE_KEY = "view_inference_analysis"
PAGE_TITLE = "Inference analysis"
PAGE_LOGO = "Inference analysis"

BASE_CHOICE_KEY = f"{PAGE_KEY}:base_choice"
CUSTOM_BASE_KEY = f"{PAGE_KEY}:custom_base"
SUBPATH_KEY = f"{PAGE_KEY}:dataset_subpath"
GLOBS_KEY = f"{PAGE_KEY}:allocation_globs"
FILES_KEY = f"{PAGE_KEY}:selected_files"
AGGREGATION_KEY = f"{PAGE_KEY}:aggregation"
PROFILE_METRIC_KEY = f"{PAGE_KEY}:profile_metric"
PROFILE_AXIS_KEY = f"{PAGE_KEY}:profile_axis"
DETAIL_RUNS_KEY = f"{PAGE_KEY}:detail_runs"
ENV_KEY = f"{PAGE_KEY}:env"
LOAD_CACHE_VERSION = 2
HEATMAP_ANNOTATION_MAX_DIM = 12
HEATMAP_MAX_COLUMNS = 2
BEARER_MAX_COLUMNS = 3
HEATMAP_GRID_COLOR = "rgba(217, 222, 231, 0.35)"

BASE_CHOICES = ("AGI_CLUSTER_SHARE", "AGILAB_EXPORT", "Custom")
AGGREGATIONS = ("mean", "sum", "median", "min", "max", "std", "count")
STEP_AXIS_CANDIDATES = ("time_index", "decision", "step", "time_idx")
TIME_AXIS_CANDIDATES = ("t_now_s", "time_s", "time", "t")
EXCLUDED_METRIC_COLUMNS = {
    "source",
    "src",
    "from",
    "destination",
    "dst",
    "dest",
    "to",
    "time_index",
    "decision",
    "step",
    "time_idx",
    "t_now_s",
    "time_s",
    "time",
    "t",
    "seed",
    "random_seed",
    "episode",
    "index",
    "row",
    "row_id",
}
PREFERRED_METRICS = (
    "delivered_bandwidth",
    "served_fraction",
    "reward",
    "latency",
    "bandwidth",
    "capacity_mbps",
    "routed",
    "path_found",
    "positive_delivery",
)
BEARER_COLOR_MAP = {
    "SAT": "#1f77b4",
    "OPT": "#2ca02c",
    "IVDL": "#ff7f0e",
    "routed/no bearer": "#9467bd",
    "not routed": "#7f7f7f",
}
BEARER_EXTRA_COLOR_SEQUENCE = (
    "#d62728",
    "#8c564b",
    "#e377c2",
    "#17becf",
    "#bcbd22",
    "#1f77b4",
    "#ff9896",
    "#98df8a",
)


def _resolve_active_app() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", dest="active_app", type=str)
    args, _ = parser.parse_known_args()

    active_app_raw = (args.active_app or "").strip()
    if not active_app_raw:
        for key in ("active_app", "active-app", "project"):
            value = st.query_params.get(key, "")
            if isinstance(value, str) and value.strip():
                active_app_raw = value.strip()
                break

    if not active_app_raw:
        st.info("Open this page from AGILAB Analysis so the active project is passed via --active-app.")
        st.stop()

    active_app_path = Path(active_app_raw).expanduser().resolve()
    if not active_app_path.exists():
        st.error(f"Provided --active-app path not found: {active_app_path}")
        st.stop()
    return active_app_path


def _load_app_settings(env: AgiEnv) -> dict[str, Any]:
    path = Path(getattr(env, "app_settings_file", "")).expanduser()
    if not path.exists():
        return {}
    try:
        with path.open("rb") as handle:
            payload = tomllib.load(handle)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _get_page_defaults(env: AgiEnv) -> dict[str, Any]:
    app_settings = _load_app_settings(env)
    pages = app_settings.get("pages")
    if not isinstance(pages, dict):
        return {}
    page_defaults = pages.get(PAGE_KEY)
    return page_defaults if isinstance(page_defaults, dict) else {}


def _coerce_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = value.replace(";", "\n").replace(",", "\n").splitlines()
    elif isinstance(value, (list, tuple, set)):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [str(value)]

    items: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        cleaned = item.strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        items.append(cleaned)
    return items


def _coerce_selection(
    saved_value: Any,
    options: list[str],
    *,
    fallback: list[str] | None = None,
) -> list[str]:
    explicit_empty = isinstance(saved_value, (list, tuple, set)) and len(saved_value) == 0
    if isinstance(saved_value, str):
        candidates = [saved_value]
    elif isinstance(saved_value, (list, tuple, set)):
        candidates = [str(item) for item in saved_value]
    else:
        candidates = []
    selected = [value for value in candidates if value in options]
    if selected or explicit_empty:
        return selected
    return [value for value in (fallback or []) if value in options]


def _default_dataset_subpath(env: AgiEnv, active_app_path: Path) -> str:
    target = str(getattr(env, "target", "") or "").strip()
    if target:
        return f"{target}/pipeline"
    name = active_app_path.name
    if name.endswith("_project"):
        return f"{name[:-8]}/pipeline"
    return "pipeline"


def _resolve_base_path(env: AgiEnv, base_choice: str, custom_base: str) -> Path | None:
    if base_choice == "AGI_CLUSTER_SHARE":
        return Path(env.share_root_path())
    if base_choice == "AGILAB_EXPORT":
        path = Path(env.AGILAB_EXPORT_ABS)
        path.mkdir(parents=True, exist_ok=True)
        return path
    cleaned = custom_base.strip()
    if not cleaned:
        return None
    return Path(cleaned).expanduser()


def _resolve_dataset_root(base_path: Path | None, dataset_subpath: str) -> Path | None:
    if base_path is None:
        return None
    rel = dataset_subpath.strip()
    return (base_path / rel).expanduser() if rel else base_path.expanduser()


def _is_hidden_relative(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts)


def _relative_path_label(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _run_label(path: Path, root: Path) -> str:
    relative = Path(_relative_path_label(path, root))
    if relative.name.startswith("allocations") and relative.parent != Path("."):
        return relative.parent.as_posix()
    return relative.as_posix()


def _discover_allocation_files(root: Path, patterns: list[str]) -> list[Path]:
    if not root.exists():
        return []
    found: set[Path] = set()
    for pattern in patterns:
        try:
            matches = root.glob(pattern)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        for candidate in matches:
            if not candidate.is_file():
                continue
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                relative = candidate
            if _is_hidden_relative(relative):
                continue
            found.add(candidate.resolve())
    return sorted(found, key=lambda path: _relative_path_label(path, root))


def _matches_any_pattern(relative_path: str, patterns: list[str]) -> bool:
    relative = relative_path.strip()
    if not relative:
        return False
    relative_obj = Path(relative)
    for pattern in patterns:
        candidate = pattern.strip()
        if not candidate:
            continue
        if fnmatch.fnmatch(relative, candidate):
            return True
        try:
            if relative_obj.match(candidate):
                return True
        except ValueError:
            continue
    return False


def _parse_structured_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped:
        return value
    for loader in (json.loads, ast.literal_eval):
        try:
            return loader(stripped)
        except Exception:
            continue
    return value


def _parse_allocations_cell(value: Any) -> list[dict[str, Any]]:
    parsed = _parse_structured_value(value)
    if parsed is None:
        return []
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, tuple):
        parsed = list(parsed)
    if not isinstance(parsed, list):
        return []

    rows: list[dict[str, Any]] = []
    for item in parsed:
        candidate = _parse_structured_value(item)
        if isinstance(candidate, dict):
            rows.append(candidate)
    return rows


def _pick_ci_column(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    lower_map = {str(col).lower(): str(col) for col in df.columns}
    for candidate in candidates:
        match = lower_map.get(candidate.lower())
        if match is not None:
            return match
    return None


def _is_scalar_like(value: Any) -> bool:
    if value is None:
        return True
    parsed = _parse_structured_value(value)
    return isinstance(parsed, (str, int, float, bool))


def _apply_column_aliases(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    src_col = _pick_ci_column(df, ("source", "src", "from"))
    dst_col = _pick_ci_column(df, ("destination", "dst", "dest", "to"))
    if src_col is not None and src_col != "source":
        df["source"] = df[src_col]
    if dst_col is not None and dst_col != "destination":
        df["destination"] = df[dst_col]

    delivered_col = _pick_ci_column(df, ("delivered_bandwidth", "delivered_mbps", "delivered_bw"))
    if delivered_col is not None and delivered_col != "delivered_bandwidth":
        df["delivered_bandwidth"] = df[delivered_col]

    latency_col = _pick_ci_column(df, ("latency", "latency_ms", "delay_ms"))
    if latency_col is not None and latency_col != "latency":
        df["latency"] = df[latency_col]

    path_col = _pick_ci_column(df, ("path", "selected_path"))
    if path_col is not None and path_col != "path":
        df["path"] = df[path_col]

    capacity_col = _pick_ci_column(df, ("capacity_mbps", "path_capacity"))
    if capacity_col is not None and capacity_col != "capacity_mbps":
        df["capacity_mbps"] = df[capacity_col]

    return df


def _coerce_time_index(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    normalized = df.copy()
    step_col = _pick_ci_column(normalized, STEP_AXIS_CANDIDATES)
    if "time_index" not in normalized.columns and step_col is not None:
        normalized["time_index"] = normalized[step_col]
    if "time_index" not in normalized.columns:
        normalized["time_index"] = pd.Series(range(len(normalized)), index=normalized.index, dtype="Int64")

    step_values = pd.to_numeric(normalized["time_index"], errors="coerce")
    if step_values.notna().any():
        if step_values.isna().any():
            fallback = pd.Series(range(len(normalized)), index=normalized.index, dtype="float64")
            step_values = step_values.combine_first(fallback)
        normalized["time_index"] = step_values.round().astype("Int64")
    else:
        normalized["time_index"] = pd.Series(range(len(normalized)), index=normalized.index, dtype="Int64")

    if "t_now_s" not in normalized.columns:
        time_col = _pick_ci_column(normalized, TIME_AXIS_CANDIDATES)
        if time_col is not None:
            time_values = pd.to_numeric(normalized[time_col], errors="coerce")
            if time_values.notna().any():
                normalized["t_now_s"] = time_values
    return normalized


def _normalize_allocations_frame(df_in: pd.DataFrame) -> pd.DataFrame:
    if df_in.empty:
        return df_in
    df = _apply_column_aliases(df_in.copy())

    alloc_col = _pick_ci_column(df, ("allocations",))
    if alloc_col is not None and ("source" not in df.columns or "destination" not in df.columns):
        step_col = _pick_ci_column(df, STEP_AXIS_CANDIDATES)
        time_col = _pick_ci_column(df, TIME_AXIS_CANDIDATES)
        exploded_rows: list[dict[str, Any]] = []

        for row_index, row in df.iterrows():
            step_context: dict[str, Any] = {}
            for column, value in row.items():
                if column == alloc_col:
                    continue
                parsed = _parse_structured_value(value)
                if _is_scalar_like(parsed):
                    step_context[column] = parsed

            if "time_index" not in step_context:
                step_context["time_index"] = row.get(step_col) if step_col is not None else row_index
            if time_col is not None and "t_now_s" not in step_context:
                step_context["t_now_s"] = row.get(time_col)

            # Carry scalar step metadata onto each nested allocation row.
            for alloc in _parse_allocations_cell(row.get(alloc_col)):
                merged = dict(step_context)
                merged.update(alloc)
                merged.setdefault("time_index", step_context.get("time_index", row_index))
                if "t_now_s" not in merged and "t_now_s" in step_context:
                    merged["t_now_s"] = step_context["t_now_s"]
                exploded_rows.append(merged)

        if exploded_rows:
            df = pd.DataFrame(exploded_rows)

    df = _apply_column_aliases(df)
    return _coerce_time_index(df)


def load_allocations(path: Path) -> pd.DataFrame:
    resolved = path.expanduser()
    if not resolved.exists():
        return pd.DataFrame()
    suffix = resolved.suffix.lower()
    try:
        if suffix == ".csv":
            return _normalize_allocations_frame(pd.read_csv(resolved))
        if suffix in {".parquet", ".pq", ".parq"}:
            return _normalize_allocations_frame(pd.read_parquet(resolved))
        if suffix in {".jsonl", ".ndjson"}:
            records: list[Any] = []
            for line in resolved.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
            return _normalize_allocations_frame(pd.DataFrame(records))

        data: Any = json.loads(resolved.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            if isinstance(data.get("allocations_steps"), list):
                data = data["allocations_steps"]
            elif isinstance(data.get("steps"), list):
                data = data["steps"]
            else:
                data = [data]
        if isinstance(data, list):
            return _normalize_allocations_frame(pd.DataFrame(data))
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame()


@st.cache_data(show_spinner=False)
def _load_allocations_cached(path_str: str, mtime_ns: int, cache_version: int) -> pd.DataFrame:
    del mtime_ns
    del cache_version
    return load_allocations(Path(path_str))


def _metric_series(df: pd.DataFrame, column: str) -> pd.Series:
    series = df[column]
    if pd.api.types.is_bool_dtype(series):
        return series.astype("float64")
    return pd.to_numeric(series, errors="coerce")


def _metric_sort_key(name: str) -> tuple[int, int, str]:
    lowered = name.lower()
    try:
        preferred_index = next(
            index for index, candidate in enumerate(PREFERRED_METRICS) if lowered == candidate.lower()
        )
        return (0, preferred_index, lowered)
    except StopIteration:
        return (1, len(PREFERRED_METRICS), lowered)


def _run_color_map(labels: list[str]) -> dict[str, str]:
    palette = px.colors.qualitative.Plotly
    return {
        label: palette[index % len(palette)]
        for index, label in enumerate(labels)
    }


def _series_varies(series: pd.Series, *, atol: float = 1e-9, rtol: float = 1e-6) -> bool:
    values = pd.to_numeric(series, errors="coerce").dropna()
    if len(values) <= 1:
        return False
    minimum = float(values.min())
    maximum = float(values.max())
    tolerance = max(atol, max(abs(minimum), abs(maximum)) * rtol)
    return (maximum - minimum) > tolerance


def discover_metric_columns(frames: dict[str, pd.DataFrame]) -> list[str]:
    metrics: set[str] = set()
    for frame in frames.values():
        if frame.empty:
            continue
        for column in frame.columns:
            if column.lower() in EXCLUDED_METRIC_COLUMNS:
                continue
            series = _metric_series(frame, column)
            if series.notna().any():
                metrics.add(column)
    return sorted(metrics, key=_metric_sort_key)


def build_profile_frame(
    frames: dict[str, pd.DataFrame],
    metric: str,
    aggregation: str,
    axis_column: str,
) -> pd.DataFrame:
    series_list: list[pd.Series] = []
    for label, frame in frames.items():
        if metric not in frame.columns or axis_column not in frame.columns:
            continue
        axis_values = pd.to_numeric(frame[axis_column], errors="coerce")
        metric_values = _metric_series(frame, metric)
        profile_df = pd.DataFrame({axis_column: axis_values, metric: metric_values}).dropna()
        if profile_df.empty:
            continue
        grouped = profile_df.groupby(axis_column, dropna=False)[metric]
        if aggregation == "mean":
            aggregated = grouped.mean()
        elif aggregation == "sum":
            aggregated = grouped.sum()
        elif aggregation == "median":
            aggregated = grouped.median()
        elif aggregation == "min":
            aggregated = grouped.min()
        elif aggregation == "max":
            aggregated = grouped.max()
        elif aggregation == "std":
            aggregated = grouped.std()
        elif aggregation == "count":
            aggregated = grouped.count()
        else:
            raise ValueError(f"Unsupported aggregation: {aggregation}")
        series_list.append(aggregated.sort_index().rename(label))
    if not series_list:
        return pd.DataFrame()
    return pd.concat(series_list, axis=1).sort_index()


def build_inventory_frame(frames: dict[str, pd.DataFrame], paths: dict[str, Path], root: Path) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for label in sorted(paths):
        path = paths[label]
        frame = frames.get(label, pd.DataFrame())
        try:
            modified = pd.Timestamp(path.stat().st_mtime, unit="s", tz="UTC").isoformat()
        except OSError:
            modified = ""
        rows.append(
            {
                "run_label": label,
                "relative_path": _relative_path_label(path, root),
                "rows": int(len(frame)),
                "steps": int(frame["time_index"].nunique(dropna=True)) if "time_index" in frame.columns else 0,
                "columns": int(len(frame.columns)),
                "modified_utc": modified,
            }
        )
    return pd.DataFrame(rows)


def _parse_list_like(value: Any) -> list[Any]:
    parsed = _parse_structured_value(value)
    if parsed is None:
        return []
    if isinstance(parsed, tuple):
        parsed = list(parsed)
    if isinstance(parsed, list):
        return parsed
    return []


def _is_missing_value(value: Any) -> bool:
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    if isinstance(result, bool):
        return result
    try:
        return bool(result)
    except (TypeError, ValueError):
        return False


def _coerce_path_sequence(value: Any) -> list[Any]:
    items = [item for item in _parse_list_like(value) if not _is_missing_value(item)]
    if len(items) == 1 and isinstance(items[0], (list, tuple)):
        return [item for item in list(items[0]) if not _is_missing_value(item)]
    return items


def _path_hop_count(value: Any) -> int | None:
    path = _coerce_path_sequence(value)
    if not path:
        return None
    if all(isinstance(item, (list, tuple)) for item in path):
        return len(path)
    if len(path) < 2:
        return None
    return len(path) - 1


def _routed_flag_series(frame: pd.DataFrame) -> pd.Series:
    if "routed" in frame.columns:
        routed = _metric_series(frame, "routed")
        return routed.fillna(0.0).clip(lower=0.0, upper=1.0)
    delivered = _metric_series(frame, "delivered_bandwidth") if "delivered_bandwidth" in frame.columns else pd.Series(0.0, index=frame.index)
    return (delivered > 0).astype("float64")


def _axis_has_numeric_values(frame: pd.DataFrame, axis_column: str) -> bool:
    if axis_column not in frame.columns:
        return False
    return bool(pd.to_numeric(frame[axis_column], errors="coerce").notna().any())


def _choose_time_series_axis(frames: dict[str, pd.DataFrame]) -> str:
    non_empty_frames = [frame for frame in frames.values() if not frame.empty]
    if not non_empty_frames:
        return ""

    preferred_axes = ("t_now_s", "time_index")
    for axis_column in preferred_axes:
        if all(_axis_has_numeric_values(frame, axis_column) for frame in non_empty_frames):
            return axis_column

    coverage = {
        axis_column: sum(_axis_has_numeric_values(frame, axis_column) for frame in non_empty_frames)
        for axis_column in preferred_axes
    }
    covered_axes = [axis_column for axis_column, count in coverage.items() if count > 0]
    if not covered_axes:
        return ""
    return max(covered_axes, key=lambda axis_column: (coverage[axis_column], axis_column == "time_index"))


def _axis_options_for_frames(frames: dict[str, pd.DataFrame]) -> list[str]:
    non_empty_frames = [frame for frame in frames.values() if not frame.empty]
    if not non_empty_frames:
        return []

    candidate_axes = ("time_index", "t_now_s")
    common_axes = [
        axis_column
        for axis_column in candidate_axes
        if all(_axis_has_numeric_values(frame, axis_column) for frame in non_empty_frames)
    ]
    if common_axes:
        return common_axes
    return [
        axis_column
        for axis_column in candidate_axes
        if any(_axis_has_numeric_values(frame, axis_column) for frame in non_empty_frames)
    ]


def build_step_kpi_frame(
    frames: dict[str, pd.DataFrame],
    axis_column: str,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for label, frame in frames.items():
        if axis_column not in frame.columns:
            continue
        axis_values = pd.to_numeric(frame[axis_column], errors="coerce")
        if axis_values.notna().sum() == 0:
            continue

        work = pd.DataFrame(index=frame.index)
        work[axis_column] = axis_values
        work["requested_bandwidth"] = (
            _metric_series(frame, "bandwidth") if "bandwidth" in frame.columns else pd.Series(0.0, index=frame.index)
        ).fillna(0.0)
        work["delivered_bandwidth"] = (
            _metric_series(frame, "delivered_bandwidth")
            if "delivered_bandwidth" in frame.columns
            else pd.Series(0.0, index=frame.index)
        ).fillna(0.0)
        work["routed_flag"] = _routed_flag_series(frame)
        latency = _metric_series(frame, "latency") if "latency" in frame.columns else pd.Series(pd.NA, index=frame.index)
        work["routed_latency"] = latency.where(work["routed_flag"] > 0)
        work = work.dropna(subset=[axis_column])
        if work.empty:
            continue

        grouped = work.groupby(axis_column, dropna=False)
        grouped_df = pd.DataFrame(
            {
                axis_column: grouped.size().index,
                "requested_bandwidth": grouped["requested_bandwidth"].sum().values,
                "delivered_bandwidth": grouped["delivered_bandwidth"].sum().values,
                "routing_rate_pct": (grouped["routed_flag"].mean() * 100.0).values,
                "mean_routed_latency": grouped["routed_latency"].mean().values,
                "allocation_count": grouped.size().values,
            }
        )
        denominator = grouped_df["requested_bandwidth"].where(grouped_df["requested_bandwidth"] > 0)
        grouped_df["served_bandwidth_pct"] = (grouped_df["delivered_bandwidth"] / denominator) * 100.0
        grouped_df["run_label"] = label
        rows.append(grouped_df)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def build_latency_distribution_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for label, frame in frames.items():
        if "latency" not in frame.columns:
            continue
        latency = _metric_series(frame, "latency")
        routed = _routed_flag_series(frame)
        subset = pd.DataFrame({"latency": latency.where(routed > 0)}).dropna()
        if subset.empty:
            continue
        subset["run_label"] = label
        rows.append(subset)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _bearer_hop_count(value: Any) -> int | None:
    bearer_values = [str(item).strip() for item in _parse_list_like(value) if str(item).strip()]
    if not bearer_values:
        return None
    return len(bearer_values)


def build_hop_count_distribution_frame(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for label, frame in frames.items():
        if "path" not in frame.columns:
            continue

        routed = _routed_flag_series(frame)
        hop_counts = [
            hop_count
            for idx in frame.index
            if routed.get(idx, 0.0) > 0
            for hop_count in [_path_hop_count(frame.at[idx, "path"])]
            if hop_count is not None
        ]
        if not hop_counts:
            continue

        counts = (
            pd.Series(hop_counts, name="hop_count")
            .value_counts()
            .sort_index()
            .rename_axis("hop_count")
            .reset_index(name="count")
        )
        total = int(counts["count"].sum())
        if total <= 0:
            continue
        counts["run_label"] = label
        counts["share_pct"] = (counts["count"] / total) * 100.0
        rows.append(counts)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def build_latency_percentile_frame(
    frames: dict[str, pd.DataFrame],
    axis_column: str,
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    percentile_specs = (
        ("p50", 0.50),
        ("p90", 0.90),
        ("p95", 0.95),
    )
    for label, frame in frames.items():
        if axis_column not in frame.columns or "latency" not in frame.columns:
            continue
        work = pd.DataFrame(index=frame.index)
        work[axis_column] = pd.to_numeric(frame[axis_column], errors="coerce")
        work["latency"] = _metric_series(frame, "latency").where(_routed_flag_series(frame) > 0)
        work = work.dropna(subset=[axis_column, "latency"])
        if work.empty:
            continue

        grouped = work.groupby(axis_column, dropna=False)["latency"]
        for percentile_label, percentile_value in percentile_specs:
            percentile_df = grouped.quantile(percentile_value).reset_index(name="latency")
            if percentile_df.empty:
                continue
            percentile_df["run_label"] = label
            percentile_df["percentile"] = percentile_label
            rows.append(percentile_df)

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def attach_latency_p90_frame(
    step_kpi_df: pd.DataFrame,
    frames: dict[str, pd.DataFrame],
    axis_column: str,
) -> pd.DataFrame:
    if step_kpi_df.empty:
        return step_kpi_df.copy()

    enriched = step_kpi_df.copy()
    enriched["p90_routed_latency"] = pd.NA

    latency_percentile_df = build_latency_percentile_frame(frames, axis_column)
    if latency_percentile_df.empty:
        return enriched

    latency_p90_df = (
        latency_percentile_df.loc[latency_percentile_df["percentile"] == "p90"]
        .drop(columns=["percentile"])
        .rename(columns={"latency": "p90_routed_latency"})
    )
    if latency_p90_df.empty:
        return enriched

    enriched = enriched.drop(columns=["p90_routed_latency"]).merge(
        latency_p90_df,
        on=[axis_column, "run_label"],
        how="left",
    )
    if "p90_routed_latency" not in enriched.columns:
        enriched["p90_routed_latency"] = pd.NA
    return enriched


def build_bearer_mix_frame(frame: pd.DataFrame, axis_column: str) -> pd.DataFrame:
    if axis_column not in frame.columns:
        return pd.DataFrame()

    axis_values = pd.to_numeric(frame[axis_column], errors="coerce")
    routed = _routed_flag_series(frame)
    rows: list[dict[str, Any]] = []
    for idx in frame.index:
        axis_value = axis_values.get(idx)
        if pd.isna(axis_value):
            continue
        bearer_values = [str(item).strip() for item in _parse_list_like(frame.at[idx, "bearers"]) if str(item).strip()] if "bearers" in frame.columns else []
        if bearer_values:
            seen: set[str] = set()
            for bearer in bearer_values:
                if bearer in seen:
                    continue
                seen.add(bearer)
                rows.append({axis_column: axis_value, "bearer": bearer, "count": 1})
        elif routed.get(idx, 0.0) > 0:
            rows.append({axis_column: axis_value, "bearer": "routed/no bearer", "count": 1})
        else:
            rows.append({axis_column: axis_value, "bearer": "not routed", "count": 1})

    if not rows:
        return pd.DataFrame()

    bearer_df = pd.DataFrame(rows)
    grouped = (
        bearer_df.groupby([axis_column, "bearer"], dropna=False)["count"]
        .sum()
        .reset_index()
        .sort_values([axis_column, "bearer"])
    )
    return grouped


def _build_bearer_involvement_figure(
    plot_df: pd.DataFrame,
    *,
    axis_name: str,
    run_label: str,
    bearer_color_map: dict[str, str],
    bearer_legend_items: Sequence[str],
) -> go.Figure:
    bearer_fig = px.area(
        plot_df,
        x=axis_name,
        y="share_pct",
        color="bearer",
        color_discrete_map=bearer_color_map,
        category_orders={"bearer": list(bearer_legend_items)},
    )
    bearer_fig.update_layout(
        title={"text": run_label, "x": 0.5, "xanchor": "center", "font": {"size": 16}},
        xaxis_title=axis_name,
        yaxis_title="Bearer involvement (%)",
        showlegend=False,
        margin={"l": 24, "r": 12, "t": 52, "b": 40},
    )
    return bearer_fig


def build_flow_heatmap_frame(frame: pd.DataFrame, *, value_kind: str) -> pd.DataFrame:
    if "source" not in frame.columns or "destination" not in frame.columns:
        return pd.DataFrame()

    work = pd.DataFrame(index=frame.index)
    work["source"] = pd.to_numeric(frame["source"], errors="coerce")
    work["destination"] = pd.to_numeric(frame["destination"], errors="coerce")
    work["requested_bandwidth"] = (
        _metric_series(frame, "bandwidth") if "bandwidth" in frame.columns else pd.Series(0.0, index=frame.index)
    ).fillna(0.0)
    work["delivered_bandwidth"] = (
        _metric_series(frame, "delivered_bandwidth")
        if "delivered_bandwidth" in frame.columns
        else pd.Series(0.0, index=frame.index)
    ).fillna(0.0)
    work["routed_flag"] = _routed_flag_series(frame)
    work = work.dropna(subset=["source", "destination"])
    if work.empty:
        return pd.DataFrame()

    grouped = work.groupby(["destination", "source"], dropna=False).agg(
        requested_bandwidth=("requested_bandwidth", "sum"),
        delivered_bandwidth=("delivered_bandwidth", "sum"),
        allocation_count=("routed_flag", "size"),
        routed_count=("routed_flag", "sum"),
    )
    grouped = grouped.reset_index()
    if grouped.empty:
        return pd.DataFrame()

    if value_kind == "served_bandwidth_pct":
        denominator = grouped["requested_bandwidth"].where(grouped["requested_bandwidth"] > 0)
        grouped["value"] = (grouped["delivered_bandwidth"] / denominator) * 100.0
    elif value_kind == "rejected_ratio_pct":
        grouped["value"] = ((grouped["allocation_count"] - grouped["routed_count"]) / grouped["allocation_count"]) * 100.0
    else:
        raise ValueError(f"Unsupported heatmap value kind: {value_kind}")

    matrix = (
        grouped.pivot(index="destination", columns="source", values="value")
        .sort_index()
        .sort_index(axis=1)
    )
    return matrix


def align_heatmap_frames(
    matrices: dict[str, pd.DataFrame],
    *,
    row_index: pd.Index | None = None,
    column_index: pd.Index | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.Index, pd.Index]:
    resolved_rows = row_index if row_index is not None else pd.Index([])
    resolved_columns = column_index if column_index is not None else pd.Index([])

    if row_index is None or column_index is None:
        for matrix in matrices.values():
            if matrix.empty:
                continue
            if row_index is None:
                resolved_rows = resolved_rows.union(matrix.index)
            if column_index is None:
                resolved_columns = resolved_columns.union(matrix.columns)

    aligned: dict[str, pd.DataFrame] = {}
    for label, matrix in matrices.items():
        if matrix.empty:
            aligned[label] = matrix
            continue
        aligned[label] = matrix.reindex(index=resolved_rows, columns=resolved_columns)
    return aligned, resolved_rows, resolved_columns


def _chunk_labels(labels: Sequence[str], *, max_columns: int) -> list[list[str]]:
    if max_columns < 1:
        raise ValueError("max_columns must be at least 1")
    return [list(labels[index:index + max_columns]) for index in range(0, len(labels), max_columns)]


def _format_heatmap_text_frame(matrix: pd.DataFrame) -> pd.DataFrame:
    formatter = lambda value: "" if pd.isna(value) else f"{float(value):.1f}"
    if hasattr(matrix, "map"):
        return matrix.map(formatter)
    return matrix.applymap(formatter)


def _resolve_heatmap_height(row_count: int) -> int:
    return max(400, min(900, 160 + 42 * row_count))


def _resolve_heatmap_section_column_count(item_count: int) -> int:
    return min(HEATMAP_MAX_COLUMNS, max(1, item_count))


def _collect_bearer_legend_items(bearer_frames: dict[str, pd.DataFrame]) -> list[str]:
    observed: set[str] = set()
    for frame in bearer_frames.values():
        if frame.empty or "bearer" not in frame.columns:
            continue
        observed.update(str(value) for value in frame["bearer"].dropna().tolist())

    ordered = [bearer for bearer in BEARER_COLOR_MAP if bearer in observed]
    extras = sorted(observed.difference(BEARER_COLOR_MAP))
    return [*ordered, *extras]


def _resolve_bearer_color_map(legend_items: Sequence[str]) -> dict[str, str]:
    color_map = dict(BEARER_COLOR_MAP)
    extras = [bearer for bearer in legend_items if bearer not in color_map]
    for index, bearer in enumerate(extras):
        color_map[bearer] = BEARER_EXTRA_COLOR_SEQUENCE[index % len(BEARER_EXTRA_COLOR_SEQUENCE)]
    return color_map


def _add_missing_bearer_legend_traces(
    fig: go.Figure,
    legend_items: Sequence[str],
    bearer_color_map: dict[str, str],
) -> None:
    existing_names = {trace.name for trace in fig.data if getattr(trace, "name", None)}
    for bearer in legend_items:
        if bearer in existing_names:
            continue
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="lines",
                name=bearer,
                line={"color": bearer_color_map[bearer], "width": 6},
                hoverinfo="skip",
                showlegend=True,
            )
        )


def _build_bearer_legend_html(
    legend_items: Sequence[str],
    bearer_color_map: dict[str, str],
) -> str:
    if not legend_items:
        return ""

    item_html = "".join(
        (
            '<span style="display:inline-flex;align-items:center;gap:0.45rem;">'
            f'<span style="width:0.9rem;height:0.9rem;display:inline-block;'
            f'background:{html.escape(bearer_color_map[bearer])};'
            'border-radius:2px;border:1px solid rgba(0,0,0,0.14);"></span>'
            f'<span>{html.escape(str(bearer))}</span>'
            "</span>"
        )
        for bearer in legend_items
    )
    return (
        '<div style="margin:0.2rem 0 0.8rem 0;">'
        '<div style="display:flex;flex-wrap:wrap;gap:0.5rem 1.2rem;align-items:center;">'
        f"{item_html}"
        "</div>"
        "</div>"
    )


def _format_heatmap_scale_label(colorbar_title: str) -> str:
    text = colorbar_title.strip()
    if not text:
        return ""
    if text.endswith(")") and " (" in text:
        head, suffix = text.rsplit(" (", 1)
        return f"**{head}**  \n({suffix}"
    return f"**{text}**"


def _build_heatmap_grid_shapes(row_count: int, column_count: int) -> list[dict[str, Any]]:
    if row_count < 1 or column_count < 1:
        return []

    grid_line = {
        "type": "line",
        "xref": "x",
        "yref": "y",
        "layer": "above",
        "line": {"color": HEATMAP_GRID_COLOR, "width": 1},
    }
    shapes: list[dict[str, Any]] = []
    max_x = column_count - 0.5
    max_y = row_count - 0.5

    for x_boundary in range(column_count + 1):
        x_coord = x_boundary - 0.5
        shapes.append(
            {
                **grid_line,
                "x0": x_coord,
                "x1": x_coord,
                "y0": -0.5,
                "y1": max_y,
            }
        )
    for y_boundary in range(row_count + 1):
        y_coord = y_boundary - 0.5
        shapes.append(
            {
                **grid_line,
                "x0": -0.5,
                "x1": max_x,
                "y0": y_coord,
                "y1": y_coord,
            }
        )
    return shapes


def _build_heatmap_figure(
    matrix: pd.DataFrame,
    *,
    title: str | None = None,
    colorbar_title: str,
    zmax: float | None = None,
    show_annotations: bool = False,
    show_colorbar: bool = True,
) -> go.Figure:
    finite_values = pd.Series(matrix.to_numpy().ravel()).dropna()
    resolved_zmax = zmax if zmax is not None else (max(100.0, float(finite_values.max())) if not finite_values.empty else 100.0)
    text = _format_heatmap_text_frame(matrix)
    x_positions = list(range(len(matrix.columns)))
    y_positions = list(range(len(matrix.index)))
    annotations_enabled = show_annotations and max(len(matrix.index), len(matrix.columns)) <= HEATMAP_ANNOTATION_MAX_DIM
    customdata = [
        [[str(row_label), str(column_label)] for column_label in matrix.columns]
        for row_label in matrix.index
    ]

    heatmap_kwargs: dict[str, Any] = {
        "z": matrix.to_numpy(dtype=float),
        "x": x_positions,
        "y": y_positions,
        "text": text.to_numpy() if annotations_enabled else None,
        "customdata": customdata,
        "texttemplate": "%{text}" if annotations_enabled else None,
        "textfont": {"size": 10},
        "colorscale": "Viridis",
        "xgap": 0,
        "ygap": 0,
        "zmin": 0.0,
        "zmax": resolved_zmax,
        "showscale": show_colorbar,
        "hovertemplate": (
            "Destination node=%{customdata[0]}<br>"
            "Source node=%{customdata[1]}<br>"
            "Value=%{z:.1f}<extra></extra>"
        ),
        "hoverongaps": False,
    }
    if show_colorbar:
        heatmap_kwargs["colorbar"] = {
            "title": {"text": colorbar_title},
            "lenmode": "fraction",
            "len": 0.72,
            "y": 0.5,
            "yanchor": "middle",
            "thickness": 14,
        }

    fig = go.Figure(data=go.Heatmap(**heatmap_kwargs))
    layout_kwargs: dict[str, Any] = {
        "margin": {"l": 20, "r": 12 if not show_colorbar else 20, "t": 50 if title else 20, "b": 56},
        "xaxis_title": "Source node",
        "yaxis_title": "Destination node",
        "xaxis": dict(
            tickmode="array",
            tickvals=x_positions,
            ticktext=[str(value) for value in matrix.columns.tolist()],
            tickangle=-45,
            automargin=True,
            constrain="domain",
        ),
        "yaxis": dict(
            tickmode="array",
            tickvals=y_positions,
            ticktext=[str(value) for value in matrix.index.tolist()],
            automargin=True,
            scaleanchor="x",
            scaleratio=1,
            constrain="domain",
        ),
        "shapes": _build_heatmap_grid_shapes(len(matrix.index), len(matrix.columns)),
        "height": _resolve_heatmap_height(len(matrix.index)),
    }
    if title:
        layout_kwargs["title"] = {"text": title, "x": 0.5, "xanchor": "center", "font": {"size": 16}}
    fig.update_layout(**layout_kwargs)
    return fig


def _build_heatmap_colorbar_figure(
    *,
    colorbar_title: str,
    zmax: float | None = None,
    height: int = 400,
) -> go.Figure:
    resolved_zmax = 100.0 if zmax is None else float(zmax)
    colorbar_config: dict[str, Any] = {
        "lenmode": "fraction",
        "len": 0.66,
        "y": 0.5,
        "yanchor": "middle",
        "x": 0.58,
        "xanchor": "right",
        "thickness": 10,
        "tickfont": {"size": 11},
    }
    if colorbar_title.strip():
        colorbar_config["title"] = {"text": colorbar_title, "side": "top"}
    fig = go.Figure(
        data=go.Scatter(
            x=[0.0, 0.0],
            y=[0.0, 1.0],
            mode="markers",
            hoverinfo="skip",
            marker={
                "size": 0.1,
                "color": [0.0, resolved_zmax],
                "colorscale": "Viridis",
                "cmin": 0.0,
                "cmax": resolved_zmax,
                "showscale": True,
                "colorbar": colorbar_config,
            },
        )
    )
    fig.update_xaxes(visible=False, fixedrange=True)
    fig.update_yaxes(visible=False, fixedrange=True)
    fig.update_layout(
        height=height,
        margin={"l": 0, "r": 28, "t": 8, "b": 8},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


def _render_heatmap(
    matrix: pd.DataFrame,
    *,
    title: str | None = None,
    colorbar_title: str,
    zmax: float | None = None,
    chart_key: str | None = None,
    show_annotations: bool = False,
    show_colorbar: bool = True,
) -> None:
    if matrix.empty:
        label = title.lower() if isinstance(title, str) and title.strip() else "this heatmap"
        st.info(f"No data available for {label}.")
        return
    fig = _build_heatmap_figure(
        matrix,
        title=title,
        colorbar_title=colorbar_title,
        zmax=zmax,
        show_annotations=show_annotations,
        show_colorbar=show_colorbar,
    )
    st.plotly_chart(fig, width="stretch", key=chart_key)


def _render_heatmap_section(
    section_title: str,
    matrices: dict[str, pd.DataFrame],
    *,
    colorbar_title: str,
    zmax: float | None = None,
    chart_key_prefix: str,
    show_annotations: bool = False,
) -> None:
    st.write(section_title)
    non_empty_matrices = [matrix for matrix in matrices.values() if not matrix.empty]
    max_row_count = max((len(matrix.index) for matrix in non_empty_matrices), default=0)
    heatmap_height = _resolve_heatmap_height(max_row_count)
    column_count = _resolve_heatmap_section_column_count(len(matrices))

    label_rows = _chunk_labels(list(matrices.keys()), max_columns=column_count)
    for row_index, row_labels in enumerate(label_rows):
        heatmap_column, legend_column = st.columns([13, 2])
        with heatmap_column:
            columns = st.columns(column_count)
            for column, label in zip(columns, row_labels):
                with column:
                    _render_heatmap(
                        matrices[label],
                        title=label,
                        colorbar_title=colorbar_title,
                        zmax=zmax,
                        chart_key=f"{chart_key_prefix}:{label}",
                        show_annotations=show_annotations,
                        show_colorbar=False,
                    )

        with legend_column:
            if non_empty_matrices:
                scale_fig = _build_heatmap_colorbar_figure(
                    colorbar_title="",
                    zmax=zmax,
                    height=heatmap_height,
                )
                st.plotly_chart(scale_fig, width="stretch", key=f"{chart_key_prefix}:scale:{row_index}")


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")

    active_app_path = _resolve_active_app()
    env = st.session_state.get(ENV_KEY)
    if not isinstance(env, AgiEnv) or Path(getattr(env, "active_app", active_app_path)).resolve() != active_app_path:
        env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
        env.init_done = True
        st.session_state[ENV_KEY] = env

    page_defaults = _get_page_defaults(env)
    default_base_choice = str(page_defaults.get("dataset_base_choice") or "AGI_CLUSTER_SHARE")
    if default_base_choice not in BASE_CHOICES:
        default_base_choice = "AGI_CLUSTER_SHARE"
    default_custom_base = str(page_defaults.get("dataset_custom_base") or "")
    default_subpath = str(
        page_defaults.get("dataset_subpath") or _default_dataset_subpath(env, active_app_path)
    )
    default_globs = _coerce_str_list(
        page_defaults.get("allocations_globs")
        or page_defaults.get("file_globs")
        or page_defaults.get("globs")
        or "**/allocations_steps.json"
    )
    default_selected_globs = _coerce_str_list(
        page_defaults.get("selected_file_globs")
        or page_defaults.get("default_selected_globs")
    )
    default_metric = str(page_defaults.get("default_metric") or "delivered_bandwidth")
    default_aggregation = str(page_defaults.get("default_aggregation") or "mean")
    if default_aggregation not in AGGREGATIONS:
        default_aggregation = "mean"
    default_profile_axis = str(page_defaults.get("default_profile_axis") or "time_index")

    st.session_state.setdefault(BASE_CHOICE_KEY, default_base_choice)
    st.session_state.setdefault(CUSTOM_BASE_KEY, default_custom_base)
    st.session_state.setdefault(SUBPATH_KEY, default_subpath)
    st.session_state.setdefault(GLOBS_KEY, "\n".join(default_globs))
    st.session_state.setdefault(AGGREGATION_KEY, default_aggregation)

    render_logo(PAGE_LOGO)
    st.title(PAGE_TITLE)
    st.caption(
        "Inspect `allocations_steps` exports across several runs without hard-coding a specific project. "
        "The page flattens nested step payloads and focuses on load, latency, bearer, and flow-level diagnostics."
    )

    with st.sidebar:
        st.header("Data source")
        st.selectbox("Base directory", BASE_CHOICES, key=BASE_CHOICE_KEY)
        st.text_input("Custom base directory", key=CUSTOM_BASE_KEY)
        st.text_input("Dataset subpath", key=SUBPATH_KEY)
        st.text_area(
            "Allocation file globs",
            help="One glob per line, relative to the resolved dataset root.",
            key=GLOBS_KEY,
        )

    base_path = _resolve_base_path(env, st.session_state[BASE_CHOICE_KEY], st.session_state[CUSTOM_BASE_KEY])
    dataset_root = _resolve_dataset_root(base_path, st.session_state[SUBPATH_KEY])
    glob_patterns = _coerce_str_list(st.session_state[GLOBS_KEY]) or ["**/allocations_steps.json"]

    if dataset_root is None:
        st.warning("Provide a custom base directory or switch back to AGI_CLUSTER_SHARE / AGILAB_EXPORT.")
        st.stop()

    st.info(f"Resolved dataset root: `{dataset_root}`")

    if not dataset_root.exists():
        st.warning(f"Dataset root does not exist yet: {dataset_root}")
        st.stop()

    allocation_files = _discover_allocation_files(dataset_root, glob_patterns)
    if not allocation_files:
        st.warning(
            f"No allocation file matched {glob_patterns!r} under {dataset_root}. "
            "Adjust the subpath or glob patterns in the sidebar."
        )
        st.stop()

    label_to_path = {_run_label(path, dataset_root): path for path in allocation_files}
    selection_options = list(label_to_path.keys())

    default_selected_labels = [
        label
        for label, path in label_to_path.items()
        if _matches_any_pattern(_relative_path_label(path, dataset_root), default_selected_globs)
    ]
    if not default_selected_labels:
        default_selected_labels = selection_options[: min(6, len(selection_options))]

    current_selected = _coerce_selection(
        st.session_state.get(FILES_KEY),
        selection_options,
        fallback=default_selected_labels,
    )
    if FILES_KEY not in st.session_state or current_selected != st.session_state.get(FILES_KEY):
        st.session_state[FILES_KEY] = current_selected

    with st.sidebar:
        st.multiselect(
            "Allocation files",
            options=selection_options,
            format_func=lambda label: label,
            key=FILES_KEY,
        )

    selected_labels = _coerce_selection(st.session_state.get(FILES_KEY), selection_options)
    if not selected_labels:
        st.info("No allocation file selected. Use the sidebar to choose one or more files.")
        with st.expander("Available file inventory", expanded=False):
            st.dataframe(build_inventory_frame({}, label_to_path, dataset_root), width="stretch", hide_index=True)
        return

    selected_paths = {label: label_to_path[label] for label in selected_labels}
    frames: dict[str, pd.DataFrame] = {}
    empty_runs: list[str] = []
    for label, path in selected_paths.items():
        frame = _load_allocations_cached(str(path), path.stat().st_mtime_ns, LOAD_CACHE_VERSION)
        frames[label] = frame
        if frame.empty:
            empty_runs.append(label)

    metric_options = discover_metric_columns(frames)
    if not metric_options:
        st.warning("The selected files loaded successfully, but no numeric metric column was found.")
        with st.expander("Loaded file inventory", expanded=False):
            st.dataframe(build_inventory_frame(frames, selected_paths, dataset_root), width="stretch", hide_index=True)
        st.stop()

    axis_options = _axis_options_for_frames(frames)
    profile_metric_options = metric_options[:]
    desired_profile_metric = st.session_state.get(PROFILE_METRIC_KEY)
    if desired_profile_metric not in profile_metric_options:
        if default_metric in profile_metric_options:
            st.session_state[PROFILE_METRIC_KEY] = default_metric
        elif "delivered_bandwidth" in profile_metric_options:
            st.session_state[PROFILE_METRIC_KEY] = "delivered_bandwidth"
        else:
            st.session_state[PROFILE_METRIC_KEY] = profile_metric_options[0]
    if axis_options:
        desired_profile_axis = st.session_state.get(PROFILE_AXIS_KEY)
        fallback_axis = default_profile_axis if default_profile_axis in axis_options else axis_options[0]
        if desired_profile_axis not in axis_options:
            st.session_state[PROFILE_AXIS_KEY] = fallback_axis

    run_color_map = _run_color_map(selected_labels)

    if empty_runs:
        st.warning("Some files were parsed but produced no rows: " + ", ".join(sorted(empty_runs)))

    time_series_axis = _choose_time_series_axis(frames)
    if time_series_axis:
        step_kpi_df = build_step_kpi_frame(frames, time_series_axis)
        if not step_kpi_df.empty:
            step_kpi_df = attach_latency_p90_frame(step_kpi_df, frames, time_series_axis)
            st.subheader("Time-series diagnostics")
            kpi_specs = [
                ("delivered_bandwidth", "Delivered bandwidth over time", "Delivered bandwidth"),
                ("served_bandwidth_pct", "Served bandwidth ratio over time", "Served bandwidth (%)"),
                ("routing_rate_pct", "Routing rate over time", "Routing rate (%)"),
                ("p90_routed_latency", "Routed latency p90 over time", "Latency p90"),
            ]
            available_specs = [
                (column_name, title, y_axis_title)
                for column_name, title, y_axis_title in kpi_specs
                if not step_kpi_df[[column_name]].dropna().empty
            ]
            if available_specs:
                cols = 2 if len(available_specs) > 1 else 1
                rows = (len(available_specs) + cols - 1) // cols
                subplot = make_subplots(
                    rows=rows,
                    cols=cols,
                    subplot_titles=[title for _, title, _ in available_specs],
                    horizontal_spacing=0.1,
                    vertical_spacing=0.16,
                )
                show_requested_reference = False
                for spec_index, (column_name, _title, y_axis_title) in enumerate(available_specs):
                    row = (spec_index // cols) + 1
                    col = (spec_index % cols) + 1
                    for run_label in selected_labels:
                        if column_name == "delivered_bandwidth":
                            requested_df = step_kpi_df.loc[
                                step_kpi_df["run_label"] == run_label,
                                [time_series_axis, "requested_bandwidth"],
                            ].dropna()
                            if not requested_df.empty and requested_df["requested_bandwidth"].abs().sum() > 0:
                                subplot.add_trace(
                                    go.Scatter(
                                        x=requested_df[time_series_axis],
                                        y=requested_df["requested_bandwidth"],
                                        mode="lines",
                                        name=f"{run_label} requested",
                                        legendgroup=run_label,
                                        showlegend=False,
                                        line=dict(
                                            color=run_color_map[run_label],
                                            dash="dash",
                                            width=1,
                                        ),
                                        hovertemplate=(
                                            f"{time_series_axis}: %{{x}}<br>"
                                            "Requested bandwidth: %{y}<extra>"
                                            f"{run_label}</extra>"
                                        ),
                                    ),
                                    row=row,
                                    col=col,
                                )
                                show_requested_reference = True
                        plot_df = step_kpi_df.loc[
                            step_kpi_df["run_label"] == run_label,
                            [time_series_axis, column_name],
                        ].dropna()
                        if plot_df.empty:
                            continue
                        subplot.add_trace(
                            go.Scatter(
                                x=plot_df[time_series_axis],
                                y=plot_df[column_name],
                                mode="lines+markers",
                                name=run_label,
                                legendgroup=run_label,
                                showlegend=spec_index == 0,
                                marker=dict(color=run_color_map[run_label]),
                                line=dict(color=run_color_map[run_label]),
                            ),
                            row=row,
                            col=col,
                        )
                    subplot.update_xaxes(title_text=time_series_axis, row=row, col=col)
                    subplot.update_yaxes(title_text=y_axis_title, row=row, col=col)
                subplot.update_layout(
                    height=max(360 * rows, 420),
                    legend=dict(
                        orientation="h",
                        yanchor="top",
	                        y=-0.16,
	                        xanchor="center",
	                        x=0.5,
	                        title_text="",
	                    ),
                    margin=dict(b=120),
                )
                st.plotly_chart(subplot, width="stretch")
                if show_requested_reference:
                    st.caption("In the delivered bandwidth panel, thin dashed traces show requested bandwidth.")

    with st.expander("Advanced: custom metric profile", expanded=False):
        st.caption("Use this when the fixed diagnostics above do not cover the metric you need.")
        if axis_options:
            control_cols = st.columns(3)
            with control_cols[0]:
                st.selectbox("Aggregation", AGGREGATIONS, key=AGGREGATION_KEY)
            with control_cols[1]:
                st.selectbox("Metric", options=profile_metric_options, key=PROFILE_METRIC_KEY)
            with control_cols[2]:
                st.selectbox("Axis", options=axis_options, key=PROFILE_AXIS_KEY)

            aggregation = str(st.session_state[AGGREGATION_KEY])
            profile_axis = str(st.session_state[PROFILE_AXIS_KEY])
            profile_metric = str(st.session_state[PROFILE_METRIC_KEY])
            profile_df = build_profile_frame(frames, profile_metric, aggregation, profile_axis)
            if profile_df.empty:
                st.info("The selected files do not expose this metric on the requested step axis.")
            else:
                profile_long = (
                    profile_df.reset_index()
                    .melt(id_vars=[profile_axis], var_name="run_label", value_name="value")
                    .dropna(subset=["value"])
                )
                profile_fig = px.line(
                    profile_long,
                    x=profile_axis,
                    y="value",
                    color="run_label",
                    markers=True,
                    category_orders={"run_label": selected_labels},
                    color_discrete_map=run_color_map,
                )
                profile_fig.update_layout(
                    title=f"{aggregation} {profile_metric} by {profile_axis}",
                    xaxis_title=profile_axis,
                    yaxis_title=f"{aggregation} {profile_metric}",
                    legend_title_text="Run",
                )
                st.plotly_chart(profile_fig, width="stretch")
        else:
            st.info("The selected files do not expose a step axis such as `time_index` or `t_now_s`.")

    detail_run_defaults = selected_labels[: min(2, len(selected_labels))]
    detail_run_current = _coerce_selection(
        st.session_state.get(DETAIL_RUNS_KEY),
        selected_labels,
        fallback=detail_run_defaults,
    )
    if DETAIL_RUNS_KEY not in st.session_state or detail_run_current != st.session_state.get(DETAIL_RUNS_KEY):
        st.session_state[DETAIL_RUNS_KEY] = detail_run_current

    st.subheader("Detailed run diagnostics")
    st.caption("Diagnostics wrap into comparable rows when several runs are selected.")
    st.multiselect("Detailed runs", options=selected_labels, key=DETAIL_RUNS_KEY)
    detail_run_labels = _coerce_selection(st.session_state.get(DETAIL_RUNS_KEY), selected_labels, fallback=detail_run_defaults)
    if not detail_run_labels:
        st.info("Select at least one detailed run to compare.")
        return

    detail_frames = {label: frames.get(label, pd.DataFrame()) for label in detail_run_labels}
    detail_axes = {
        label: (
            "t_now_s"
            if "t_now_s" in frame.columns
            else ("time_index" if "time_index" in frame.columns else "")
        )
        for label, frame in detail_frames.items()
    }
    detail_bearer_mix = {
        label: (build_bearer_mix_frame(frame, detail_axes[label]) if detail_axes[label] else pd.DataFrame())
        for label, frame in detail_frames.items()
    }
    hop_count_distribution_df = build_hop_count_distribution_frame(detail_frames)
    detail_served_heatmaps = {
        label: build_flow_heatmap_frame(frame, value_kind="served_bandwidth_pct")
        for label, frame in detail_frames.items()
    }
    detail_rejected_heatmaps = {
        label: build_flow_heatmap_frame(frame, value_kind="rejected_ratio_pct")
        for label, frame in detail_frames.items()
    }
    heatmap_nodes = pd.Index([])
    for matrix in [*detail_served_heatmaps.values(), *detail_rejected_heatmaps.values()]:
        if matrix.empty:
            continue
        heatmap_nodes = heatmap_nodes.union(matrix.index).union(matrix.columns)
    detail_served_heatmaps, _, _ = align_heatmap_frames(
        detail_served_heatmaps,
        row_index=heatmap_nodes,
        column_index=heatmap_nodes,
    )
    detail_rejected_heatmaps, _, _ = align_heatmap_frames(
        detail_rejected_heatmaps,
        row_index=heatmap_nodes,
        column_index=heatmap_nodes,
    )

    served_max_candidates = [
        float(pd.Series(matrix.to_numpy().ravel()).dropna().max())
        for matrix in detail_served_heatmaps.values()
        if not matrix.empty and not pd.Series(matrix.to_numpy().ravel()).dropna().empty
    ]
    served_heatmap_zmax = max([100.0, *served_max_candidates]) if served_max_candidates else 100.0
    rejected_heatmap_zmax = 100.0

    st.write("Bearer involvement")
    bearer_column_count = min(BEARER_MAX_COLUMNS, max(1, len(detail_run_labels)))
    bearer_label_rows = _chunk_labels(detail_run_labels, max_columns=bearer_column_count)
    bearer_legend_items = _collect_bearer_legend_items(detail_bearer_mix)
    bearer_color_map = _resolve_bearer_color_map(bearer_legend_items)
    bearer_legend_html = _build_bearer_legend_html(bearer_legend_items, bearer_color_map)
    if bearer_legend_html:
        st.markdown(bearer_legend_html, unsafe_allow_html=True)
    for row_labels in bearer_label_rows:
        bearer_cols = st.columns(bearer_column_count)
        for index, (column, label) in enumerate(zip(bearer_cols, row_labels)):
            with column:
                axis_name = detail_axes[label]
                bearer_mix_df = detail_bearer_mix[label]
                if not axis_name or bearer_mix_df.empty:
                    st.info(f"{label}: No bearer involvement data available.")
                    continue
                plot_df = bearer_mix_df.copy()
                totals = plot_df.groupby(axis_name)["count"].transform("sum")
                plot_df["share_pct"] = (plot_df["count"] / totals.where(totals > 0)) * 100.0
                plot_df = plot_df.dropna(subset=["share_pct"])
                if plot_df.empty:
                    st.info(f"{label}: No bearer involvement data available.")
                    continue
                bearer_fig = _build_bearer_involvement_figure(
                    plot_df,
                    axis_name=axis_name,
                    run_label=label,
                    bearer_color_map=bearer_color_map,
                    bearer_legend_items=bearer_legend_items,
                )
                st.plotly_chart(
                    bearer_fig,
                    width="stretch",
                    key=f"{PAGE_KEY}:detail:bearer:{label}",
                )

    if hop_count_distribution_df.empty:
        st.info("No routed path data available.")
    else:
        hop_count_fig = px.bar(
            hop_count_distribution_df,
            x="hop_count",
            y="share_pct",
            color="run_label",
            barmode="group",
            category_orders={"run_label": detail_run_labels},
            color_discrete_map=run_color_map,
        )
        hop_count_fig.update_layout(
            title={"text": "Routed hop count distribution", "x": 0.5, "xanchor": "center", "font": {"size": 16}},
            xaxis_title="Hop count",
            yaxis_title="Routed allocations (%)",
            legend_title_text="Run",
            margin={"l": 24, "r": 12, "t": 50, "b": 40},
        )
        hop_count_fig.update_xaxes(dtick=1)
        hop_count_fig.update_traces(
            hovertemplate=(
                "Run=%{fullData.name}<br>"
                "Hop count=%{x}<br>"
                "Routed allocations=%{y:.1f}%<extra></extra>"
            )
        )
        st.plotly_chart(
            hop_count_fig,
            width="stretch",
            key=f"{PAGE_KEY}:detail:hop_count_distribution",
        )
        st.caption("Hop count is computed as `len(path) - 1` on routed allocations with a valid path.")

    _render_heatmap_section(
        "Served bandwidth matrix",
        detail_served_heatmaps,
        colorbar_title="Served bandwidth (%)",
        zmax=served_heatmap_zmax,
        chart_key_prefix=f"{PAGE_KEY}:detail:served_heatmap",
    )
    _render_heatmap_section(
        "Rejected allocation matrix",
        detail_rejected_heatmaps,
        colorbar_title="Rejected ratio (%)",
        zmax=rejected_heatmap_zmax,
        chart_key_prefix=f"{PAGE_KEY}:detail:rejected_heatmap",
    )
    if not heatmap_nodes.empty:
        st.caption(
            "Matrices use one shared node list across all selected runs. Axes show source and destination nodes, "
            "while the internal layout keeps uniform cell sizes. Exact values are available on hover, and the shared color scale is rendered separately on the right of each matrix row. "
            "Blank cells mean no data for that source-destination pair in that run."
        )


if __name__ == "__main__":
    main()
