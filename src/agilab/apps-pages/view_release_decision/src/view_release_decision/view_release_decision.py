# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
import importlib.util
import json
import shlex
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
MANIFEST_INDEX_FILENAME = "manifest_index.json"
MANIFEST_INDEX_SCHEMA = "agilab.manifest_index.v1"
FIRST_PROOF_PATH_ID = "source-checkout-first-proof"
REQUIRED_FIRST_PROOF_VALIDATIONS = ("proof_steps", "target_seconds", "recommended_project")
APP_DEFAULT_METRICS_GLOBS = {
    "meteo_forecast_project": "**/forecast_metrics.json",
}
APP_DEFAULT_REQUIRED_PATTERNS = {
    "meteo_forecast_project": ("forecast_metrics.json", "forecast_predictions.csv"),
}


def _load_run_manifest_module() -> Any:
    here = Path(__file__).resolve()
    for parent in here.parents:
        module_path = parent / "agilab" / "run_manifest.py"
        if module_path.is_file():
            spec = importlib.util.spec_from_file_location(
                "agilab_run_manifest_for_release_decision",
                module_path,
            )
            if not spec or not spec.loader:
                break
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            return module
    raise ModuleNotFoundError("Unable to load agilab/run_manifest.py for release decisions.")


_run_manifest_module = _load_run_manifest_module()
RUN_MANIFEST_FILENAME = _run_manifest_module.RUN_MANIFEST_FILENAME
load_run_manifest = _run_manifest_module.load_run_manifest
manifest_passed = _run_manifest_module.manifest_passed
manifest_summary = _run_manifest_module.manifest_summary


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


def _default_run_manifest_path(env: AgiEnv) -> Path:
    log_root = Path(getattr(env, "AGILAB_LOG_ABS", Path.home() / "log")).expanduser()
    return log_root / "execute" / "flight" / RUN_MANIFEST_FILENAME


def _dedupe_paths(paths: list[tuple[Path, str]]) -> list[tuple[Path, str]]:
    seen: set[str] = set()
    deduped: list[tuple[Path, str]] = []
    for path, provenance in paths:
        expanded = path.expanduser()
        key = str(expanded.resolve()) if expanded.exists() else str(expanded.absolute())
        if key in seen:
            continue
        seen.add(key)
        deduped.append((expanded, provenance))
    return deduped


def _parse_manifest_import_args(raw_value: str) -> tuple[list[Path], list[Path], list[dict[str, str]]]:
    if not raw_value.strip():
        return [], [], []
    try:
        tokens = shlex.split(raw_value)
    except ValueError as exc:
        return [], [], [{"source": "import args", "detail": f"Unable to parse manifest import args: {exc}"}]

    manifest_paths: list[Path] = []
    manifest_dirs: list[Path] = []
    errors: list[dict[str, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in {"--manifest", "--manifest-dir"}:
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                errors.append({"source": token, "detail": f"{token} requires a path value"})
                index += 1
                continue
            target = Path(tokens[index + 1]).expanduser()
            if token == "--manifest":
                manifest_paths.append(target)
            else:
                manifest_dirs.append(target)
            index += 2
            continue
        if token.startswith("--manifest="):
            manifest_paths.append(Path(token.split("=", 1)[1]).expanduser())
        elif token.startswith("--manifest-dir="):
            manifest_dirs.append(Path(token.split("=", 1)[1]).expanduser())
        index += 1

    return manifest_paths, manifest_dirs, errors


def _discover_imported_manifest_paths(
    manifest_paths: list[Path],
    manifest_dirs: list[Path],
) -> tuple[list[tuple[Path, str]], list[dict[str, str]]]:
    discovered: list[tuple[Path, str]] = [
        (path, "--manifest")
        for path in manifest_paths
    ]
    errors: list[dict[str, str]] = []
    for directory in manifest_dirs:
        directory = directory.expanduser()
        if directory.is_file():
            discovered.append((directory, f"--manifest-dir {directory}"))
        elif directory.is_dir():
            discovered.extend(
                (path, f"--manifest-dir {directory}")
                for path in sorted(directory.rglob(RUN_MANIFEST_FILENAME))
            )
        else:
            errors.append(
                {
                    "source": str(directory),
                    "detail": "manifest directory not found",
                }
            )
    return _dedupe_paths(discovered), errors


def _build_manifest_import_rows(raw_value: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_paths, manifest_dirs, parse_errors = _parse_manifest_import_args(raw_value)
    discovered, discovery_errors = _discover_imported_manifest_paths(manifest_paths, manifest_dirs)
    rows: list[dict[str, Any]] = [
        {
            "source": error["source"],
            "provenance": "import-args",
            "path_id": "",
            "run_id": "",
            "manifest_status": "invalid",
            "evidence_status": "invalid",
            "duration_seconds": None,
            "target_seconds": None,
            "validation_statuses": "",
            "detail": error["detail"],
            "loaded": False,
        }
        for error in [*parse_errors, *discovery_errors]
    ]

    for path, provenance in discovered:
        base_row: dict[str, Any] = {
            "source": str(path),
            "provenance": provenance,
            "path_id": "",
            "run_id": "",
            "manifest_status": "invalid",
            "evidence_status": "invalid",
            "duration_seconds": None,
            "target_seconds": None,
            "validation_statuses": "",
            "detail": "",
            "loaded": False,
        }
        try:
            manifest = load_run_manifest(path)
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            rows.append({**base_row, "detail": f"Unable to load run manifest: {exc}"})
            continue

        validation_statuses = {
            validation.label: validation.status
            for validation in manifest.validations
        }
        passed = bool(manifest_passed(manifest))
        rows.append(
            {
                **base_row,
                "path_id": manifest.path_id,
                "run_id": manifest.run_id,
                "manifest_status": manifest.status,
                "evidence_status": "validated" if passed else "failed",
                "duration_seconds": manifest.timing.duration_seconds,
                "target_seconds": manifest.timing.target_seconds,
                "validation_statuses": ", ".join(
                    f"{label}={status}"
                    for label, status in validation_statuses.items()
                ),
                "detail": "loaded",
                "loaded": True,
            }
        )

    summary = {
        "args": raw_value,
        "requested_manifest_count": len(manifest_paths),
        "requested_manifest_dir_count": len(manifest_dirs),
        "discovered_manifest_count": len(discovered),
        "loaded_manifest_count": sum(1 for row in rows if row["loaded"]),
        "validated_manifest_count": sum(1 for row in rows if row["evidence_status"] == "validated"),
        "failed_manifest_count": sum(1 for row in rows if row["evidence_status"] == "failed"),
        "invalid_manifest_count": sum(1 for row in rows if row["evidence_status"] == "invalid"),
    }
    return rows, summary


def _select_run_manifest_gate_path(default_path: Path, imported_rows: list[dict[str, Any]]) -> Path:
    loaded_first_proof_rows = [
        row
        for row in imported_rows
        if row.get("loaded") and row.get("path_id") == FIRST_PROOF_PATH_ID and row.get("source")
    ]
    validated_rows = [
        row
        for row in loaded_first_proof_rows
        if row.get("evidence_status") == "validated"
    ]
    selected = (validated_rows or loaded_first_proof_rows)[:1]
    if selected:
        return Path(str(selected[0]["source"])).expanduser()
    return default_path


def _manifest_index_path(artifact_root: Path) -> Path:
    return artifact_root.expanduser() / MANIFEST_INDEX_FILENAME


def _load_manifest_index(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser()
    empty_index = {
        "schema": MANIFEST_INDEX_SCHEMA,
        "generated_at": None,
        "artifact_root": str(path.parent),
        "releases": {},
    }
    if not path.exists():
        return empty_index, {
            "path": str(path),
            "loaded": False,
            "error": "missing",
            "release_count": 0,
            "manifest_count": 0,
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("manifest index must be a JSON object")
        if payload.get("schema") != MANIFEST_INDEX_SCHEMA:
            raise ValueError(f"unsupported manifest index schema: {payload.get('schema')!r}")
        releases = payload.get("releases", {})
        if not isinstance(releases, dict):
            raise ValueError("manifest index releases must be an object")
        payload["releases"] = releases
        manifest_count = sum(
            len(release.get("manifests", []))
            for release in releases.values()
            if isinstance(release, dict)
        )
        return payload, {
            "path": str(path),
            "loaded": True,
            "error": None,
            "release_count": len(releases),
            "manifest_count": manifest_count,
        }
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return empty_index, {
            "path": str(path),
            "loaded": False,
            "error": str(exc),
            "release_count": 0,
            "manifest_count": 0,
        }


def _build_manifest_index_record(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": row.get("source", ""),
        "provenance": row.get("provenance", ""),
        "path_id": row.get("path_id", ""),
        "run_id": row.get("run_id", ""),
        "manifest_status": row.get("manifest_status", ""),
        "evidence_status": row.get("evidence_status", ""),
        "duration_seconds": row.get("duration_seconds"),
        "target_seconds": row.get("target_seconds"),
        "validation_statuses": row.get("validation_statuses", ""),
        "loaded": bool(row.get("loaded")),
        "detail": row.get("detail", ""),
    }


def _build_manifest_index_release(
    *,
    artifact_root: Path,
    baseline_path: Path,
    candidate_path: Path,
    run_manifest_path: Path,
    run_manifest_summary: dict[str, Any],
    imported_manifest_rows: list[dict[str, Any]],
    imported_manifest_summary: dict[str, Any],
) -> dict[str, Any]:
    candidate_bundle = candidate_path.parent
    baseline_bundle = baseline_path.parent
    return {
        "release_id": candidate_bundle.name,
        "artifact_root": str(artifact_root),
        "candidate_bundle_root": str(candidate_bundle),
        "baseline_bundle_root": str(baseline_bundle),
        "candidate_metrics_file": str(candidate_path),
        "baseline_metrics_file": str(baseline_path),
        "selected_run_manifest_path": str(run_manifest_path),
        "selected_run_manifest_summary": run_manifest_summary,
        "import_summary": imported_manifest_summary,
        "manifests": [
            _build_manifest_index_record(row)
            for row in imported_manifest_rows
        ],
    }


def _merge_manifest_index(
    existing_index: dict[str, Any],
    *,
    artifact_root: Path,
    release: dict[str, Any],
) -> dict[str, Any]:
    releases = dict(existing_index.get("releases", {}))
    releases[str(release["candidate_bundle_root"])] = release
    return {
        "schema": MANIFEST_INDEX_SCHEMA,
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "artifact_root": str(artifact_root),
        "releases": releases,
    }


def _manifest_index_summary(index: dict[str, Any], *, path: Path, loaded: bool, error: str | None) -> dict[str, Any]:
    releases = index.get("releases", {})
    manifest_rows = [
        manifest
        for release in releases.values()
        if isinstance(release, dict)
        for manifest in release.get("manifests", [])
        if isinstance(manifest, dict)
    ]
    return {
        "path": str(path),
        "loaded": True,
        "error": None,
        "existing_index_loaded": loaded,
        "existing_index_error": error,
        "release_count": len(releases),
        "manifest_count": len(manifest_rows),
        "validated_manifest_count": sum(
            1 for row in manifest_rows if row.get("evidence_status") == "validated"
        ),
        "failed_manifest_count": sum(
            1 for row in manifest_rows if row.get("evidence_status") == "failed"
        ),
        "invalid_manifest_count": sum(
            1 for row in manifest_rows if row.get("evidence_status") == "invalid"
        ),
    }


def _manifest_index_rows(index: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    releases = index.get("releases", {})
    for release_key, release in sorted(releases.items()):
        if not isinstance(release, dict):
            continue
        for manifest in release.get("manifests", []):
            if not isinstance(manifest, dict):
                continue
            rows.append(
                {
                    "release": release.get("release_id", Path(str(release_key)).name),
                    "candidate_bundle": release.get("candidate_bundle_root", release_key),
                    "source": manifest.get("source", ""),
                    "provenance": manifest.get("provenance", ""),
                    "path_id": manifest.get("path_id", ""),
                    "run_id": manifest.get("run_id", ""),
                    "manifest_status": manifest.get("manifest_status", ""),
                    "evidence_status": manifest.get("evidence_status", ""),
                    "duration_seconds": manifest.get("duration_seconds"),
                    "target_seconds": manifest.get("target_seconds"),
                }
            )
    return rows


def _write_manifest_index(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


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
                    "flight_run_count": None,
                    "aircraft_count": None,
                    "aircraft": "",
                    "output_file_count": None,
                    "output_files": "",
                    "output_formats": "",
                    "speed_count": None,
                    "mean_speed_m": None,
                    "max_speed_m": None,
                    "time_start": "",
                    "time_end": "",
                    "scenario_count": None,
                    "scenarios": "",
                    "packets_generated": None,
                    "packets_delivered": None,
                    "packets_dropped": None,
                    "pdr": None,
                    "mean_e2e_delay_ms": None,
                    "mean_queue_wait_ms": None,
                    "max_queue_depth_pkts": None,
                    "forecast_run_count": None,
                    "stations": "",
                    "targets": "",
                    "model_names": "",
                    "prediction_rows": None,
                    "backtest_rows": None,
                    "forecast_rows": None,
                    "mae": None,
                    "rmse": None,
                    "mape": None,
                    "horizon_days": "",
                    "validation_days": "",
                    "lags": "",
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
                "flight_run_count": artifact_payload.get("flight_run_count"),
                "aircraft_count": artifact_payload.get("aircraft_count"),
                "aircraft": _comma_joined(artifact_payload.get("aircraft")),
                "output_file_count": artifact_payload.get("output_file_count"),
                "output_files": _comma_joined(artifact_payload.get("output_files")),
                "output_formats": _comma_joined(artifact_payload.get("output_formats")),
                "speed_count": artifact_payload.get("speed_count"),
                "mean_speed_m": artifact_payload.get("mean_speed_m"),
                "max_speed_m": artifact_payload.get("max_speed_m"),
                "time_start": artifact_payload.get("time_start"),
                "time_end": artifact_payload.get("time_end"),
                "scenario_count": artifact_payload.get("scenario_count"),
                "scenarios": _comma_joined(artifact_payload.get("scenarios")),
                "packets_generated": artifact_payload.get("packets_generated"),
                "packets_delivered": artifact_payload.get("packets_delivered"),
                "packets_dropped": artifact_payload.get("packets_dropped"),
                "pdr": artifact_payload.get("pdr"),
                "mean_e2e_delay_ms": artifact_payload.get("mean_e2e_delay_ms"),
                "mean_queue_wait_ms": artifact_payload.get("mean_queue_wait_ms"),
                "max_queue_depth_pkts": artifact_payload.get("max_queue_depth_pkts"),
                "forecast_run_count": artifact_payload.get("forecast_run_count"),
                "stations": _comma_joined(artifact_payload.get("stations")),
                "targets": _comma_joined(artifact_payload.get("targets")),
                "model_names": _comma_joined(artifact_payload.get("model_names")),
                "prediction_rows": artifact_payload.get("prediction_rows"),
                "backtest_rows": artifact_payload.get("backtest_rows"),
                "forecast_rows": artifact_payload.get("forecast_rows"),
                "mae": artifact_payload.get("mae"),
                "rmse": artifact_payload.get("rmse"),
                "mape": artifact_payload.get("mape"),
                "horizon_days": _comma_joined(artifact_payload.get("horizon_days")),
                "validation_days": _comma_joined(artifact_payload.get("validation_days")),
                "lags": _comma_joined(artifact_payload.get("lags")),
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


def _build_run_manifest_gate_rows(manifest_path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest_path = manifest_path.expanduser()
    base_summary: dict[str, Any] = {
        "path": str(manifest_path),
        "loaded": False,
        "error": None,
    }
    try:
        manifest = load_run_manifest(manifest_path)
    except FileNotFoundError:
        return (
            [
                {
                    "gate": "run_manifest_present",
                    "status": "fail",
                    "detail": f"Missing first-proof run manifest: {manifest_path}",
                }
            ],
            {**base_summary, "error": "missing"},
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return (
            [
                {
                    "gate": "run_manifest_valid",
                    "status": "fail",
                    "detail": f"Invalid first-proof run manifest: {exc}",
                }
            ],
            {**base_summary, "error": str(exc)},
        )

    summary = {
        **base_summary,
        **manifest_summary(manifest),
        "loaded": True,
        "validation_count": len(manifest.validations),
    }
    validation_statuses = {
        validation.label: validation.status
        for validation in manifest.validations
    }
    missing_validations = [
        label
        for label in REQUIRED_FIRST_PROOF_VALIDATIONS
        if label not in validation_statuses
    ]
    validations_ok = (
        manifest_passed(manifest)
        and not missing_validations
        and all(status == "pass" for status in validation_statuses.values())
    )
    target = manifest.timing.target_seconds
    target_ok = target is not None and manifest.timing.duration_seconds <= target
    rows = [
        {
            "gate": "run_manifest_status",
            "status": "pass" if manifest.status == "pass" else "fail",
            "detail": f"manifest status is {manifest.status!r}",
        },
        {
            "gate": "run_manifest_path_id",
            "status": "pass" if manifest.path_id == FIRST_PROOF_PATH_ID else "fail",
            "detail": f"manifest path_id is {manifest.path_id!r}",
        },
        {
            "gate": "run_manifest_validations",
            "status": "pass" if validations_ok else "fail",
            "detail": (
                "all required validations passed"
                if validations_ok
                else f"validation statuses={validation_statuses}, missing={missing_validations}"
            ),
        },
        {
            "gate": "run_manifest_target_seconds",
            "status": "pass" if target_ok else "fail",
            "detail": (
                f"duration {manifest.timing.duration_seconds:.2f}s <= target {target:.2f}s"
                if target_ok
                else f"duration={manifest.timing.duration_seconds:.2f}s target={target}"
            ),
        },
    ]
    return rows, summary


def _decision_status(
    baseline_path: Path,
    candidate_path: Path,
    artifact_rows: list[dict[str, Any]],
    metric_rows: list[dict[str, Any]],
    manifest_rows: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    if baseline_path == candidate_path:
        return "needs_review", "Baseline and candidate point to the same metrics file."
    if any(row["status"] == "fail" for row in manifest_rows or []):
        return "blocked", "First-proof run manifest gate is failing or missing."
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
    run_manifest_path: Path,
    run_manifest_rows: list[dict[str, Any]],
    run_manifest_summary: dict[str, Any],
    imported_manifest_rows: list[dict[str, Any]],
    imported_manifest_summary: dict[str, Any],
    manifest_index_path: Path,
    manifest_index_summary: dict[str, Any],
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
        "run_manifest_path": str(run_manifest_path),
        "run_manifest_summary": run_manifest_summary,
        "run_manifest_gates": run_manifest_rows,
        "run_manifest_import_summary": imported_manifest_summary,
        "imported_run_manifest_evidence": imported_manifest_rows,
        "manifest_index_path": str(manifest_index_path),
        "manifest_index_summary": manifest_index_summary,
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
run_manifest_path_value = st.sidebar.text_input(
    "First-proof run manifest",
    value=st.session_state.setdefault(
        "release_decision_run_manifest_path",
        str(_default_run_manifest_path(env)),
    ),
    key="release_decision_run_manifest_path",
)
default_run_manifest_path = Path(run_manifest_path_value).expanduser()
manifest_import_args_value = st.sidebar.text_area(
    "Imported run manifest evidence",
    value=st.session_state.setdefault("release_decision_manifest_import_args", ""),
    key="release_decision_manifest_import_args",
    height=90,
    help=(
        "Paste compatibility-report style args such as "
        "`--manifest /path/run_manifest.json --manifest-dir /path/to/evidence`."
    ),
)
imported_manifest_rows, imported_manifest_summary = _build_manifest_import_rows(
    manifest_import_args_value
)
run_manifest_path = _select_run_manifest_gate_path(
    default_run_manifest_path,
    imported_manifest_rows,
)
if run_manifest_path != default_run_manifest_path:
    st.sidebar.caption(f"Using imported first-proof manifest: {run_manifest_path}")

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
run_manifest_rows, run_manifest_summary = _build_run_manifest_gate_rows(run_manifest_path)
manifest_index_path = _manifest_index_path(artifact_root)
existing_manifest_index, existing_manifest_index_summary = _load_manifest_index(manifest_index_path)
current_manifest_index_release = _build_manifest_index_release(
    artifact_root=artifact_root,
    baseline_path=baseline_path,
    candidate_path=candidate_path,
    run_manifest_path=run_manifest_path,
    run_manifest_summary=run_manifest_summary,
    imported_manifest_rows=imported_manifest_rows,
    imported_manifest_summary=imported_manifest_summary,
)
manifest_index_payload = _merge_manifest_index(
    existing_manifest_index,
    artifact_root=artifact_root,
    release=current_manifest_index_release,
)
manifest_index_summary = _manifest_index_summary(
    manifest_index_payload,
    path=manifest_index_path,
    loaded=bool(existing_manifest_index_summary.get("loaded")),
    error=existing_manifest_index_summary.get("error"),
)
decision_status, decision_summary = _decision_status(
    baseline_path=baseline_path,
    candidate_path=candidate_path,
    artifact_rows=artifact_rows,
    metric_rows=metric_rows,
    manifest_rows=run_manifest_rows,
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
    run_manifest_path=run_manifest_path,
    run_manifest_rows=run_manifest_rows,
    run_manifest_summary=run_manifest_summary,
    imported_manifest_rows=imported_manifest_rows,
    imported_manifest_summary=imported_manifest_summary,
    manifest_index_path=manifest_index_path,
    manifest_index_summary=manifest_index_summary,
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

manifest_df = pd.DataFrame(run_manifest_rows)
st.subheader("First-proof run manifest gate")
st.caption(str(run_manifest_path))
st.dataframe(manifest_df, width="stretch", hide_index=True)

if imported_manifest_rows:
    imported_manifest_df = pd.DataFrame(imported_manifest_rows)
    st.subheader("Imported run manifest evidence")
    st.caption(
        "External evidence imported with compatibility-report style `--manifest` and `--manifest-dir` inputs."
    )
    st.dataframe(imported_manifest_df, width="stretch", hide_index=True)

manifest_index_rows = _manifest_index_rows(manifest_index_payload)
st.subheader("Per-release manifest index")
st.caption(str(manifest_index_path))
if manifest_index_rows:
    st.dataframe(pd.DataFrame(manifest_index_rows), width="stretch", hide_index=True)
else:
    st.info("No imported run manifests are indexed for this artifact root yet.")

metric_df = pd.DataFrame(metric_rows)
if metric_df.empty:
    st.info("No shared numeric metrics were available for an automatic KPI gate.")
else:
    st.subheader("KPI gates")
    st.dataframe(metric_df, width="stretch", hide_index=True)

decision_path = candidate_path.parent / "promotion_decision.json"
if st.button("Export promotion decision", type="primary", use_container_width=True):
    written = _write_decision(decision_path, payload)
    written_index = _write_manifest_index(manifest_index_path, manifest_index_payload)
    st.success(f"Promotion decision exported to {written}; manifest index exported to {written_index}")

st.download_button(
    "Download decision JSON",
    data=json.dumps(payload, indent=2, sort_keys=True),
    file_name="promotion_decision.json",
    mime="application/json",
    use_container_width=True,
)
