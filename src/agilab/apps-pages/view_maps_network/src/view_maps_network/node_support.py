from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

try:
    from allocation_support import safe_literal_eval
except ModuleNotFoundError:  # pragma: no cover - package import path
    from .allocation_support import safe_literal_eval

logger = logging.getLogger(__name__)
_TRAILING_EXPORT_TIMESTAMP_RE = re.compile(r"[_-]\d{4}-\d{2}-\d{2}(?:[_-]\d{2}-\d{2}-\d{2})?$")

def _normalize_node_id_series(series: pd.Series) -> pd.Series:
    """Normalize node IDs for consistent matching and drop invalid placeholders."""
    raw = series.copy()
    num = pd.to_numeric(raw, errors="coerce")
    out = raw.astype("string").fillna("").astype(str).str.strip()
    mask_int = num.notna() & np.isclose(num % 1, 0.0)
    if mask_int.any():
        out.loc[mask_int] = num.loc[mask_int].round().astype(int).astype(str)
    invalid = out.str.lower().isin({"", "nan", "none", "nat", "<na>"})
    out.loc[invalid] = ""
    return out


def _normalize_node_id_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "nat", "<na>"}:
        return ""
    try:
        num = float(s)
        if np.isfinite(num) and np.isclose(num % 1, 0.0):
            return str(int(round(num)))
    except (TypeError, ValueError, OverflowError):
        logger.debug("Node id %r is not an integer-like value", value, exc_info=True)
    return s


def _strip_export_suffix(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = _TRAILING_EXPORT_TIMESTAMP_RE.sub("", text)
    return re.sub(r"[-_](trajectory|traj)$", "", text, flags=re.IGNORECASE)


def _semantic_node_id_from_text(value: Any) -> str | None:
    text = _strip_export_suffix(value)
    if not text:
        return None
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits:
        return None
    try:
        return str(int(digits))
    except ValueError:
        return None


def _preferred_node_id_from_row(row: pd.Series, *, source_path: str | None = None) -> str:
    semantic_columns = (
        "plane_label",
        "sat_name",
        "plane_type",
        "name",
        "callsign",
        "call_sign",
        "stable_flight_id",
        "node_label",
        "trajectory_label",
    )
    for col in semantic_columns:
        if col not in row:
            continue
        semantic_id = _semantic_node_id_from_text(row.get(col))
        if semantic_id:
            return semantic_id

    source_value = row.get("source_file") if "source_file" in row else source_path
    if source_value not in (None, ""):
        semantic_id = _semantic_node_id_from_text(Path(str(source_value)).stem)
        if semantic_id:
            return semantic_id

    for col in ("plane_id", "trajectory_id", "node_id", "flight_id", "id_col", "id"):
        if col not in row:
            continue
        normalized = _normalize_node_id_value(row.get(col))
        if normalized:
            return normalized
    return ""


def _candidate_node_ids(value: Any) -> list[str]:
    base = _normalize_node_id_value(value)
    if not base:
        return []
    candidates = [base]
    semantic_id = _semantic_node_id_from_text(value)
    if semantic_id:
        candidates.append(semantic_id)
    prefixes = ("plane_", "sat_", "uav_", "node_")
    lowered = base.lower()
    for prefix in prefixes:
        if lowered.startswith(prefix):
            stripped = _normalize_node_id_value(base[len(prefix) :])
            if stripped:
                candidates.append(stripped)
            break
    for prefix in prefixes:
        candidates.append(prefix + base)
    deduped: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        if cand and cand not in seen:
            seen.add(cand)
            deduped.append(cand)
    return deduped


def _resolve_node_id(value: Any, node_set: set[str]) -> str | None:
    for cand in _candidate_node_ids(value):
        if cand in node_set:
            return cand
    return None


def _coerce_list_cell(value: Any) -> list[Any]:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        parsed = safe_literal_eval(value)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, tuple):
            return list(parsed)
    return []


def _allocation_visible_node_ids(*frames: pd.DataFrame) -> set[str]:
    visible_nodes: set[str] = set()
    for df_in in frames:
        if df_in is None or df_in.empty:
            continue
        for col in ("source", "destination"):
            if col in df_in.columns:
                visible_nodes.update(node_id for node_id in _normalize_node_id_series(df_in[col]).tolist() if node_id)
        if "path" not in df_in.columns:
            continue
        for raw_path in df_in["path"].tolist():
            for hop in _coerce_list_cell(raw_path):
                hop_items = _coerce_list_cell(hop)
                node_values = hop_items[:2] if len(hop_items) >= 2 else [hop]
                for node in node_values:
                    node_id = _normalize_node_id_value(node)
                    if node_id:
                        visible_nodes.add(node_id)
    return visible_nodes


def _allocation_endpoint_roles(
    *frames: pd.DataFrame,
    focus_pair: tuple[int, int] | None = None,
) -> dict[str, str]:
    if focus_pair is not None:
        src = _normalize_node_id_value(focus_pair[0])
        dst = _normalize_node_id_value(focus_pair[1])
        roles = {}
        if src:
            roles[src] = "src"
        if dst:
            roles[dst] = "dst"
        return roles

    pairs: set[tuple[str, str]] = set()
    for df_in in frames:
        if df_in is None or df_in.empty or not {"source", "destination"} <= set(df_in.columns):
            continue
        src_ids = _normalize_node_id_series(df_in["source"])
        dst_ids = _normalize_node_id_series(df_in["destination"])
        for src, dst in zip(src_ids.tolist(), dst_ids.tolist()):
            if src and dst:
                pairs.add((src, dst))
    if len(pairs) != 1:
        return {}
    src, dst = next(iter(pairs))
    roles = {src: "src"}
    if dst != src:
        roles[dst] = "dst"
    return roles


def _format_node_label(value: Any, node_roles: dict[str, str] | None = None) -> str:
    node_id = _normalize_node_id_value(value)
    if not node_id:
        return ""
    role = (node_roles or {}).get(node_id)
    if role:
        return f"{node_id} ({role})"
    return node_id


def _coerce_numeric_float(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not np.isfinite(num):
        return None
    return float(num)


def _coerce_numeric_int(value: Any) -> int | None:
    num = _coerce_numeric_float(value)
    if num is None:
        return None
    return int(round(num))


def _filter_allocation_rows_for_selected_nodes(
    df_in: pd.DataFrame,
    selected_nodes: set[str],
    *,
    sample_time: Any = None,
    step_hint: Any = None,
) -> pd.DataFrame:
    if df_in.empty or not selected_nodes or not {"source", "destination"} <= set(df_in.columns):
        return pd.DataFrame()

    src_ids = _normalize_node_id_series(df_in["source"])
    dst_ids = _normalize_node_id_series(df_in["destination"])
    filtered = df_in.loc[src_ids.isin(selected_nodes) & dst_ids.isin(selected_nodes)].copy()
    if filtered.empty:
        return filtered

    sample_time_num = _coerce_numeric_float(sample_time)
    time_col = "time_s" if "time_s" in filtered.columns else "t_now_s" if "t_now_s" in filtered.columns else None
    if sample_time_num is not None and time_col is not None:
        t_series = pd.to_numeric(filtered[time_col], errors="coerce")
        valid_times = sorted({float(v) for v in t_series.dropna().tolist()})
        if valid_times:
            nearest_time = min(valid_times, key=lambda value: abs(value - sample_time_num))
            filtered = filtered.loc[t_series == nearest_time].copy()
            if not filtered.empty:
                return filtered

    step_num = _coerce_numeric_int(step_hint)
    if step_num is not None and "time_index" in filtered.columns:
        step_series = pd.to_numeric(filtered["time_index"], errors="coerce")
        valid_steps = sorted({int(round(float(v))) for v in step_series.dropna().tolist()})
        if valid_steps:
            nearest_step = min(valid_steps, key=lambda value: abs(value - step_num))
            filtered = filtered.loc[step_series.round() == nearest_step].copy()

    return filtered


def _canonical_edge_pair(source: Any, target: Any) -> tuple[str, str] | None:
    source_id = _normalize_node_id_value(source)
    target_id = _normalize_node_id_value(target)
    if not source_id or not target_id or source_id == target_id:
        return None
    return tuple(sorted((source_id, target_id)))
