# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

import pandas as pd
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
from agi_env.pagelib import render_logo
from agi_node.reduction import ReduceArtifact

LOWER_IS_BETTER_KEYWORDS = ("mae", "rmse", "mape", "loss", "error", "latency", "duration")
HIGHER_IS_BETTER_KEYWORDS = ("accuracy", "f1", "precision", "recall", "throughput", "score", "auc", "r2")
REDUCE_ARTIFACT_GLOB = "**/reduce_summary_worker_*.json"
APP_DEFAULT_METRICS_GLOBS = {
    "meteo_forecast_project": "**/forecast_metrics.json",
}
APP_DEFAULT_REQUIRED_PATTERNS = {
    "meteo_forecast_project": ("forecast_metrics.json", "forecast_predictions.csv"),
}


def _resolve_active_app() -> Path:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", dest="active_app", type=str, required=True)
    args, _ = parser.parse_known_args()
    active_app_path = Path(args.active_app).expanduser().resolve()
    if not active_app_path.exists():
        st.error(f"Provided --active-app path not found: {active_app_path}")
        st.stop()
    return active_app_path


def _default_artifact_root(env: AgiEnv) -> Path:
    return Path(env.AGILAB_EXPORT_ABS) / env.target


def _default_metrics_glob(env: AgiEnv) -> str:
    return APP_DEFAULT_METRICS_GLOBS.get(str(env.app), "**/*metrics*.json")


def _default_required_patterns(env: AgiEnv) -> list[str]:
    patterns = APP_DEFAULT_REQUIRED_PATTERNS.get(str(env.app))
    if patterns:
        return list(patterns)
    return ["*.json"]


def _discover_files(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted((path for path in base.glob(pattern) if path.is_file()), key=lambda path: path.as_posix())
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def _sort_key_with_mtime(path: Path) -> tuple[int, str]:
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return mtime, path.as_posix()


def _default_metric_file_selection(paths: list[Path]) -> tuple[int, int]:
    if not paths:
        return 0, 0
    ordered = sorted(enumerate(paths), key=lambda item: _sort_key_with_mtime(item[1]))
    candidate_index = ordered[-1][0]
    baseline_index = ordered[-2][0] if len(ordered) > 1 else candidate_index
    return baseline_index, candidate_index


def _load_metrics(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Metrics payload must be a JSON object: {path}")
    return payload


def _relative_display_path(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _comma_joined(value: Any) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _build_reduce_artifact_rows(
    artifact_root: Path,
    pattern: str = REDUCE_ARTIFACT_GLOB,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in _discover_files(artifact_root, pattern):
        base_row: dict[str, Any] = {
            "artifact": _relative_display_path(path, artifact_root),
            "path": str(path),
        }
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            artifact = ReduceArtifact.from_dict(payload)
            artifact_payload = artifact.payload
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            rows.append(
                {
                    **base_row,
                    "status": "invalid",
                    "name": "",
                    "reducer": "",
                    "partial_count": None,
                    "source_file_count": None,
                    "row_count": None,
                    "result_rows": None,
                    "engines": "",
                    "execution_models": "",
                    "detail": str(exc),
                }
            )
            continue

        rows.append(
            {
                **base_row,
                "status": "pass",
                "name": artifact.name,
                "reducer": artifact.reducer,
                "partial_count": artifact.partial_count,
                "source_file_count": artifact_payload.get("source_file_count"),
                "row_count": artifact_payload.get("row_count"),
                "result_rows": artifact_payload.get("result_rows"),
                "engines": _comma_joined(artifact_payload.get("engines")),
                "execution_models": _comma_joined(artifact_payload.get("execution_models")),
                "detail": "Reduce artifact parsed.",
            }
        )
    return rows


def _flatten_numeric_metrics(payload: dict[str, Any], prefix: str = "") -> dict[str, float]:
    flattened: dict[str, float] = {}
    for key, value in payload.items():
        metric_name = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, dict):
            flattened.update(_flatten_numeric_metrics(value, metric_name))
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            flattened[metric_name] = float(value)
    return flattened


def _metadata_subset(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            result[str(key)] = value
    return result


def _metric_direction(metric_name: str) -> str:
    lowered = metric_name.lower()
    if any(keyword in lowered for keyword in LOWER_IS_BETTER_KEYWORDS):
        return "lower"
    if any(keyword in lowered for keyword in HIGHER_IS_BETTER_KEYWORDS):
        return "higher"
    return "unknown"


def _build_metric_rows(
    baseline_metrics: dict[str, float],
    candidate_metrics: dict[str, float],
    tolerance_pct: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for metric_name in sorted(set(baseline_metrics) & set(candidate_metrics)):
        baseline = baseline_metrics[metric_name]
        candidate = candidate_metrics[metric_name]
        direction = _metric_direction(metric_name)
        delta = candidate - baseline
        delta_pct = None if baseline == 0 else (delta / baseline) * 100.0
        status = "review"
        detail = "Metric direction is not standardized yet."
        if direction == "lower":
            limit = baseline * (1.0 + tolerance_pct / 100.0)
            status = "pass" if candidate <= limit else "fail"
            detail = f"Candidate must stay <= {limit:.4f}."
        elif direction == "higher":
            limit = baseline * (1.0 - tolerance_pct / 100.0)
            status = "pass" if candidate >= limit else "fail"
            detail = f"Candidate must stay >= {limit:.4f}."
        rows.append(
            {
                "metric": metric_name,
                "direction": direction,
                "baseline": baseline,
                "candidate": candidate,
                "delta": delta,
                "delta_pct": delta_pct,
                "status": status,
                "detail": detail,
            }
        )
    return rows


def _build_artifact_rows(
    baseline_root: Path,
    candidate_root: Path,
    required_patterns: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for pattern in required_patterns:
        baseline_matches = _discover_files(baseline_root, pattern)
        candidate_matches = _discover_files(candidate_root, pattern)
        rows.append(
            {
                "pattern": pattern,
                "baseline_count": len(baseline_matches),
                "candidate_count": len(candidate_matches),
                "status": "pass" if candidate_matches else "fail",
                "detail": "Required candidate artifacts present." if candidate_matches else "Missing from candidate bundle.",
            }
        )
    return rows


def _decision_status(
    baseline_path: Path,
    candidate_path: Path,
    artifact_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
) -> tuple[str, str]:
    if baseline_path == candidate_path:
        return "needs_review", "Baseline and candidate point to the same metrics file."
    if any(row["status"] == "fail" for row in artifact_rows):
        return "blocked", "Required evidence artifacts are missing from the candidate bundle."
    if any(row["status"] == "fail" for row in metric_rows):
        return "blocked", "At least one standardized KPI regressed beyond the allowed tolerance."
    if any(row["status"] == "pass" for row in metric_rows):
        return "promotable", "All explicit gates passed against the selected baseline."
    return "needs_review", "No standardized KPI gate was available; review manually before promotion."


def _decision_payload(
    env: AgiEnv,
    artifact_root: Path,
    baseline_path: Path,
    candidate_path: Path,
    baseline_payload: dict[str, Any],
    candidate_payload: dict[str, Any],
    artifact_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    reduce_artifact_rows: list[dict[str, Any]],
    status: str,
    summary: str,
    tolerance_pct: float,
) -> dict[str, Any]:
    return {
        "schema": "agilab.promotion.decision.v1",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "app": str(env.app),
        "target": str(env.target),
        "artifact_root": str(artifact_root),
        "baseline_metrics_file": str(baseline_path),
        "candidate_metrics_file": str(candidate_path),
        "baseline_bundle_root": str(baseline_path.parent),
        "candidate_bundle_root": str(candidate_path.parent),
        "status": status,
        "summary": summary,
        "tolerance_pct": tolerance_pct,
        "baseline_metadata": _metadata_subset(baseline_payload),
        "candidate_metadata": _metadata_subset(candidate_payload),
        "artifact_gates": artifact_rows,
        "metric_gates": metric_rows,
        "reduce_artifacts": reduce_artifact_rows,
    }


def _write_decision(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


st.set_page_config(layout="wide")

if "env" not in st.session_state:
    active_app_path = _resolve_active_app()
    env = AgiEnv(apps_path=active_app_path.parent, app=active_app_path.name, verbose=0)
    env.init_done = True
    st.session_state["env"] = env
else:
    env = st.session_state["env"]

render_logo("Release Decision")
st.title("Release decision")
st.caption(
    "Compare a candidate bundle against a baseline, apply explicit evidence gates, and export a promotion decision."
)

default_root = _default_artifact_root(env)
artifact_root_value = st.sidebar.text_input(
    "Artifact directory",
    value=st.session_state.setdefault("release_decision_datadir", str(default_root)),
    key="release_decision_datadir",
)
artifact_root = Path(artifact_root_value).expanduser()

metrics_pattern = st.sidebar.text_input(
    "Metrics glob",
    value=st.session_state.setdefault("release_decision_metrics_glob", _default_metrics_glob(env)),
    key="release_decision_metrics_glob",
)
required_patterns_value = st.sidebar.text_area(
    "Required artifact patterns",
    value=st.session_state.setdefault(
        "release_decision_required_patterns",
        "\n".join(_default_required_patterns(env)),
    ),
    key="release_decision_required_patterns",
    height=100,
)
tolerance_pct = float(
    st.sidebar.number_input(
        "Allowed regression tolerance (%)",
        min_value=0.0,
        max_value=100.0,
        value=float(st.session_state.setdefault("release_decision_tolerance_pct", 0.0)),
        step=1.0,
        key="release_decision_tolerance_pct",
    )
)
required_patterns = [line.strip() for line in required_patterns_value.splitlines() if line.strip()]

if not artifact_root.exists():
    st.warning(f"Artifact directory does not exist yet: {artifact_root}")
    st.stop()

reduce_artifact_rows = _build_reduce_artifact_rows(artifact_root)
st.subheader("Reduce artifacts")
if reduce_artifact_rows:
    reduce_artifact_df = pd.DataFrame(reduce_artifact_rows)
    st.dataframe(reduce_artifact_df, width="stretch", hide_index=True)
else:
    st.info(
        "No `reduce_summary_worker_*.json` artifacts found under the selected artifact directory."
    )

metrics_files = _discover_files(artifact_root, metrics_pattern)
if not metrics_files:
    st.warning(f"No metrics file found in {artifact_root} with pattern {metrics_pattern!r}.")
    st.stop()

default_baseline_index, default_candidate_index = _default_metric_file_selection(metrics_files)
baseline_path = Path(
    st.sidebar.selectbox(
        "Baseline metrics file",
        options=metrics_files,
        index=default_baseline_index,
        format_func=lambda path: str(Path(path).relative_to(artifact_root)),
    )
)
candidate_path = Path(
    st.sidebar.selectbox(
        "Candidate metrics file",
        options=metrics_files,
        index=default_candidate_index,
        format_func=lambda path: str(Path(path).relative_to(artifact_root)),
    )
)

try:
    baseline_payload = _load_metrics(baseline_path)
    candidate_payload = _load_metrics(candidate_path)
except (OSError, ValueError, json.JSONDecodeError) as exc:
    st.error(f"Unable to load selected metrics payloads: {exc}")
    st.stop()

baseline_metrics = _flatten_numeric_metrics(baseline_payload)
candidate_metrics = _flatten_numeric_metrics(candidate_payload)
metric_rows = _build_metric_rows(baseline_metrics, candidate_metrics, tolerance_pct=tolerance_pct)
artifact_rows = _build_artifact_rows(baseline_path.parent, candidate_path.parent, required_patterns)
decision_status, decision_summary = _decision_status(
    baseline_path=baseline_path,
    candidate_path=candidate_path,
    artifact_rows=artifact_rows,
    metric_rows=metric_rows,
)
payload = _decision_payload(
    env=env,
    artifact_root=artifact_root,
    baseline_path=baseline_path,
    candidate_path=candidate_path,
    baseline_payload=baseline_payload,
    candidate_payload=candidate_payload,
    artifact_rows=artifact_rows,
    metric_rows=metric_rows,
    reduce_artifact_rows=reduce_artifact_rows,
    status=decision_status,
    summary=decision_summary,
    tolerance_pct=tolerance_pct,
)

if decision_status == "promotable":
    st.success(f"Promotable: {decision_summary}")
elif decision_status == "blocked":
    st.error(f"Blocked: {decision_summary}")
else:
    st.warning(f"Needs review: {decision_summary}")

meta_left, meta_right = st.columns(2)
with meta_left:
    st.subheader("Baseline bundle")
    st.caption(str(baseline_path.parent))
    st.json(_metadata_subset(baseline_payload))
with meta_right:
    st.subheader("Candidate bundle")
    st.caption(str(candidate_path.parent))
    st.json(_metadata_subset(candidate_payload))

artifact_df = pd.DataFrame(artifact_rows)
st.subheader("Evidence gates")
st.dataframe(artifact_df, width="stretch", hide_index=True)

metric_df = pd.DataFrame(metric_rows)
if metric_df.empty:
    st.info("No shared numeric metrics were available for an automatic KPI gate.")
else:
    st.subheader("KPI gates")
    st.dataframe(metric_df, width="stretch", hide_index=True)

decision_path = candidate_path.parent / "promotion_decision.json"
if st.button("Export promotion decision", type="primary", use_container_width=True):
    written = _write_decision(decision_path, payload)
    st.success(f"Promotion decision exported to {written}")

st.download_button(
    "Download decision JSON",
    data=json.dumps(payload, indent=2, sort_keys=True),
    file_name="promotion_decision.json",
    mime="application/json",
    use_container_width=True,
)
