# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

"""Side-effect-free Scenario Cockpit evidence helpers."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


EVIDENCE_SCHEMA = "agilab.scenario_evidence_bundle.v1"
PEER_ARTIFACT_SUFFIXES = (
    "queue_timeseries",
    "packet_events",
    "node_positions",
    "routing_summary",
)
PIPELINE_ARTIFACTS = (
    "pipeline/topology.gml",
    "pipeline/allocations_steps.csv",
    "pipeline/_trajectory_summary.json",
)


def discover_files(base: Path, pattern: str) -> list[Path]:
    try:
        return sorted([path for path in base.glob(pattern) if path.is_file()], key=lambda p: p.as_posix())
    except (OSError, RuntimeError, TypeError, ValueError):
        return []


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def peer_file(path: Path, suffix: str) -> Path:
    stem = path.name.removesuffix("_summary_metrics.json")
    return path.with_name(f"{stem}_{suffix}.csv")


def relative_label(path: Path, artifact_root: Path) -> str:
    try:
        return str(path.relative_to(artifact_root))
    except (RuntimeError, TypeError, ValueError):
        return path.name


def scenario_row(summary_path: Path, artifact_root: Path) -> dict[str, Any]:
    summary = load_json(summary_path)
    return {
        "run_label": relative_label(summary_path, artifact_root),
        "scenario": summary.get("scenario", ""),
        "routing_policy": summary.get("routing_policy", ""),
        "bond_mode": summary.get("bond_mode", "single"),
        "source_rate_pps": summary.get("source_rate_pps"),
        "random_seed": summary.get("random_seed"),
        "pdr": summary.get("pdr"),
        "mean_e2e_delay_ms": summary.get("mean_e2e_delay_ms"),
        "mean_queue_wait_ms": summary.get("mean_queue_wait_ms"),
        "max_queue_depth_pkts": summary.get("max_queue_depth_pkts"),
        "bottleneck_relay": summary.get("bottleneck_relay", ""),
        "summary_path": str(summary_path),
    }


def build_comparison_frame(
    selected_paths: dict[str, Path],
    artifact_root: Path,
    baseline_label: str,
) -> pd.DataFrame:
    rows = [scenario_row(path, artifact_root) for path in selected_paths.values()]
    if not rows:
        return pd.DataFrame()
    comparison_df = pd.DataFrame(rows)
    numeric_columns = [
        "source_rate_pps",
        "random_seed",
        "pdr",
        "mean_e2e_delay_ms",
        "mean_queue_wait_ms",
        "max_queue_depth_pkts",
    ]
    for column in numeric_columns:
        comparison_df[column] = pd.to_numeric(comparison_df[column], errors="coerce")
    if baseline_label in comparison_df["run_label"].values:
        baseline_row = comparison_df.loc[comparison_df["run_label"] == baseline_label].iloc[0]
        comparison_df["delta_pdr_vs_baseline"] = comparison_df["pdr"] - baseline_row["pdr"]
        comparison_df["delta_delay_ms_vs_baseline"] = (
            comparison_df["mean_e2e_delay_ms"] - baseline_row["mean_e2e_delay_ms"]
        )
        comparison_df["delta_queue_wait_ms_vs_baseline"] = (
            comparison_df["mean_queue_wait_ms"] - baseline_row["mean_queue_wait_ms"]
        )
        comparison_df["delta_max_queue_vs_baseline"] = (
            comparison_df["max_queue_depth_pkts"] - baseline_row["max_queue_depth_pkts"]
        )
    ordered_columns = [
        "run_label",
        "scenario",
        "routing_policy",
        "bond_mode",
        "source_rate_pps",
        "random_seed",
        "pdr",
        "mean_e2e_delay_ms",
        "mean_queue_wait_ms",
        "max_queue_depth_pkts",
        "bottleneck_relay",
        "delta_pdr_vs_baseline",
        "delta_delay_ms_vs_baseline",
        "delta_queue_wait_ms_vs_baseline",
        "delta_max_queue_vs_baseline",
        "summary_path",
    ]
    return comparison_df[[column for column in ordered_columns if column in comparison_df.columns]]


def safe_float(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return numeric


def json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    if pd.isna(value):
        return None
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    return str(value)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_record(path: Path, artifact_root: Path) -> dict[str, Any]:
    record: dict[str, Any] = {
        "path": str(path),
        "relative_path": relative_label(path, artifact_root),
        "exists": path.is_file(),
    }
    if path.is_file():
        record["sha256"] = hash_file(path)
        record["bytes"] = path.stat().st_size
    return record


def evidence_artifacts(summary_path: Path, artifact_root: Path) -> list[dict[str, Any]]:
    run_dir = summary_path.parent
    artifact_paths = [summary_path]
    artifact_paths.extend(peer_file(summary_path, suffix) for suffix in PEER_ARTIFACT_SUFFIXES)
    artifact_paths.extend(run_dir / relative for relative in PIPELINE_ARTIFACTS)
    for trajectory in discover_files(run_dir / "pipeline", "*_trajectory*.csv"):
        if trajectory not in artifact_paths:
            artifact_paths.append(trajectory)
    return [artifact_record(path, artifact_root) for path in artifact_paths]


def candidate_gate(comparison_df: pd.DataFrame, candidate_label: str) -> dict[str, Any]:
    if comparison_df.empty or candidate_label not in set(comparison_df.get("run_label", [])):
        return {
            "candidate": candidate_label,
            "status": "missing-candidate",
            "checks": [],
        }
    candidate = comparison_df.loc[comparison_df["run_label"] == candidate_label].iloc[0]
    check_specs = [
        ("pdr_not_lower", candidate.get("delta_pdr_vs_baseline"), "greater_or_equal"),
        ("delay_not_higher", candidate.get("delta_delay_ms_vs_baseline"), "less_or_equal"),
        ("queue_wait_not_higher", candidate.get("delta_queue_wait_ms_vs_baseline"), "less_or_equal"),
        ("max_queue_not_higher", candidate.get("delta_max_queue_vs_baseline"), "less_or_equal"),
    ]
    checks: list[dict[str, Any]] = []
    for name, raw_value, direction in check_specs:
        value = safe_float(raw_value)
        if value is None:
            passed = False
        elif direction == "greater_or_equal":
            passed = value >= 0
        else:
            passed = value <= 0
        checks.append(
            {
                "name": name,
                "delta": value,
                "direction": direction,
                "passed": passed,
            }
        )
    status = "promotable" if checks and all(check["passed"] for check in checks) else "needs-review"
    return {
        "candidate": candidate_label,
        "status": status,
        "checks": checks,
    }


def build_evidence_bundle(
    *,
    selected_paths: dict[str, Path],
    artifact_root: Path,
    comparison_df: pd.DataFrame,
    baseline_label: str,
    candidate_label: str,
) -> dict[str, Any]:
    artifacts: list[dict[str, Any]] = []
    for path in selected_paths.values():
        artifacts.extend(evidence_artifacts(path, artifact_root))
    selected_runs = comparison_df.drop(columns=["summary_path"], errors="ignore").to_dict(orient="records")
    return json_safe(
        {
            "schema": EVIDENCE_SCHEMA,
            "generated_at": datetime.now(UTC).isoformat(),
            "source_page": "view_scenario_cockpit",
            "artifact_root": str(artifact_root),
            "baseline_run": baseline_label,
            "candidate_run": candidate_label,
            "gate": candidate_gate(comparison_df, candidate_label),
            "selected_runs": selected_runs,
            "artifacts": artifacts,
        }
    )


__all__ = [
    "EVIDENCE_SCHEMA",
    "PIPELINE_ARTIFACTS",
    "PEER_ARTIFACT_SUFFIXES",
    "artifact_record",
    "build_comparison_frame",
    "build_evidence_bundle",
    "candidate_gate",
    "discover_files",
    "evidence_artifacts",
    "hash_file",
    "json_safe",
    "load_json",
    "peer_file",
    "relative_label",
    "safe_float",
    "scenario_row",
]
