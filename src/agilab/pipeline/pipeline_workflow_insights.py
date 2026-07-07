"""Workflow cockpit insight helpers for AGILAB lab stages.

The functions in this module are deliberately Streamlit-free so WORKFLOW can
render richer dashboards without coupling the calculations to page state.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


PIPELINE_WORKFLOW_INSIGHTS_SCHEMA = "agilab.pipeline.workflow_insights.v1"
PIPELINE_AUTOPILOT_PREFLIGHT_SCHEMA = "agilab.pipeline.autopilot_preflight.v1"
_MODEL_SUFFIXES = {".joblib", ".pkl", ".pickle", ".pt", ".pth", ".onnx", ".zip"}
_METADATA_SUFFIXES = {".json", ".toml", ".yaml", ".yml"}
_PATH_LITERAL_RE = re.compile(
    r"(?P<key>data_in|data_out|inputs?|outputs?|model_path|artifact_path)\s*=\s*['\"](?P<path>[^'\"]+)['\"]"
)
_DICT_PATH_RE = re.compile(
    r"['\"](?P<key>data_in|data_out|inputs?|outputs?|model_path|artifact_path)['\"]\s*:\s*['\"](?P<path>[^'\"]+)['\"]"
)
_PANDAS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("inplace", re.compile(r"\binplace\s*=\s*True\b")),
    ("chained-assignment", re.compile(r"\][ \t]*\[[^\n\]]+\][ \t]*=(?!=)")),
    ("copy-deep-false", re.compile(r"\.copy\s*\([^\n)]*deep\s*=\s*False")),
    ("copy-on-write-option", re.compile(r"mode\.copy_on_write")),
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _iter_path_values(value: Any) -> Iterable[str]:
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, Path):
        yield str(value)
        return
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            yield stripped
        return
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            yield from _iter_path_values(value[key])
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_path_values(item)


def _path_kind(key: str) -> str:
    normalized = key.lower()
    if "out" in normalized:
        return "output"
    if "model" in normalized or "artifact" in normalized:
        return "artifact"
    return "input"


def stage_path_specs(stage: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return declared and code-literal path specs for one stage."""

    specs: list[dict[str, str]] = []
    direct_keys = (
        "data_in",
        "data_out",
        "input",
        "inputs",
        "input_paths",
        "output",
        "outputs",
        "output_paths",
        "model_path",
        "artifact_path",
    )
    for key in direct_keys:
        if key in stage:
            for path in _iter_path_values(stage.get(key)):
                specs.append({"kind": _path_kind(key), "source": key, "path": path})
    automation = _as_mapping(stage.get("automation"))
    for key in ("inputs", "input_paths", "outputs", "output_paths"):
        if key in automation:
            for path in _iter_path_values(automation.get(key)):
                specs.append({"kind": _path_kind(key), "source": f"automation.{key}", "path": path})
    code = _clean_text(stage.get("C"))
    for pattern in (_PATH_LITERAL_RE, _DICT_PATH_RE):
        for match in pattern.finditer(code):
            specs.append(
                {
                    "kind": _path_kind(match.group("key")),
                    "source": f"code.{match.group('key')}",
                    "path": match.group("path"),
                }
            )
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, str]] = []
    for spec in specs:
        key = (spec["kind"], spec["source"], spec["path"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(spec)
    return unique


def _candidate_paths(raw_path: str, roots: Sequence[Path]) -> list[Path]:
    raw = raw_path.strip()
    if not raw:
        return []
    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        return [expanded]
    candidates = [root / expanded for root in roots if root]
    candidates.append(expanded)
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        text = str(candidate)
        if text not in seen:
            seen.add(text)
            unique.append(candidate)
    return unique


def _first_existing_path(raw_path: str, roots: Sequence[Path]) -> Path | None:
    for candidate in _candidate_paths(raw_path, roots):
        try:
            if candidate.exists():
                return candidate
        except OSError:
            continue
    return None


def build_data_availability(
    stages: Sequence[Mapping[str, Any]],
    sequence: Sequence[int],
    roots: Sequence[Path],
    *,
    input_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for idx in sequence:
        if not 0 <= int(idx) < len(stages):
            continue
        stage = stages[int(idx)]
        for spec in stage_path_specs(stage):
            spec_roots = input_roots if spec["kind"] == "input" and input_roots is not None else roots
            existing = _first_existing_path(spec["path"], spec_roots)
            rows.append(
                {
                    "stage": int(idx) + 1,
                    "kind": spec["kind"],
                    "source": spec["source"],
                    "path": spec["path"],
                    "status": "present" if existing else "missing",
                    "resolved_path": str(existing or ""),
                }
            )
    counts = Counter(row["status"] for row in rows)
    missing_inputs = [row for row in rows if row["kind"] == "input" and row["status"] == "missing"]
    missing_outputs = [row for row in rows if row["kind"] == "output" and row["status"] == "missing"]
    recommendations: list[str] = []
    if missing_inputs:
        recommendations.append("Generate or select upstream input artifacts before running dependent stages.")
    if missing_outputs:
        recommendations.append("Declared outputs are not present yet; run the producing stages or inspect the latest manifest.")
    if not rows:
        recommendations.append("No stage data paths are declared; add data_in/data_out or automation input/output metadata for stronger preflight checks.")
    return {
        "rows": rows,
        "total": len(rows),
        "present": counts.get("present", 0),
        "missing": counts.get("missing", 0),
        "missing_inputs": missing_inputs,
        "missing_outputs": missing_outputs,
        "recommendations": recommendations,
    }


def build_workflow_quality(
    stages: Sequence[Mapping[str, Any]],
    sequence: Sequence[int],
    waves: Sequence[Sequence[int]],
    stage_ids: Mapping[int, str],
    stage_deps: Mapping[str, Sequence[str]],
    *,
    dependency_error: str | None = None,
) -> dict[str, Any]:
    waits: list[dict[str, Any]] = []
    for idx in sequence:
        stage_id = stage_ids.get(int(idx), f"stage_{int(idx) + 1}")
        deps = list(stage_deps.get(stage_id, []))
        waits.append({"stage": int(idx) + 1, "stage_id": stage_id, "waits_for": deps})
    parallel_width = max((len(wave) for wave in waves), default=0)
    sequential_steps = len(sequence)
    critical_steps = len(waves) if waves else sequential_steps
    saved_steps = max(0, sequential_steps - critical_steps)
    explicit_dependency_count = sum(len(row["waits_for"]) for row in waits)
    return {
        "schema": PIPELINE_WORKFLOW_INSIGHTS_SCHEMA,
        "stage_count": len(sequence),
        "wave_count": len(waves),
        "parallel_width": parallel_width,
        "critical_steps": critical_steps,
        "sequential_steps": sequential_steps,
        "saved_steps": saved_steps,
        "explicit_dependency_count": explicit_dependency_count,
        "dependency_status": "blocked" if dependency_error else "ready",
        "dependency_error": dependency_error or "",
        "waits": waits,
    }


def _manifest_output_summary(manifest: Mapping[str, Any] | None) -> dict[str, int]:
    outputs = []
    if manifest:
        raw_outputs = manifest.get("outputs") or manifest.get("output_evidence") or []
        if isinstance(raw_outputs, list):
            outputs = [item for item in raw_outputs if isinstance(item, Mapping)]
    return {
        "outputs": len(outputs),
        "existing": sum(1 for item in outputs if bool(item.get("exists") or item.get("existing"))),
        "hashed": sum(1 for item in outputs if bool(item.get("sha256") or item.get("hash"))),
    }


def build_evidence_score(
    *,
    quality: Mapping[str, Any],
    data_availability: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
    model_artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    score = 0
    reasons: list[str] = []
    if int(quality.get("stage_count", 0) or 0) > 0:
        score += 15
        reasons.append("stages selected")
    if quality.get("dependency_status") == "ready" and int(quality.get("wave_count", 0) or 0) > 0:
        score += 20
        reasons.append("dependency waves computed")
    if int(quality.get("explicit_dependency_count", 0) or 0) > 0:
        score += 10
        reasons.append("explicit dependencies declared")
    manifest_status = _clean_text(manifest.get("status") if manifest else "")
    if manifest:
        score += 20
        reasons.append("automation manifest available")
        if manifest_status in {"success", "succeeded", "completed", "done"}:
            score += 10
            reasons.append("latest manifest reports success")
    output_summary = _manifest_output_summary(manifest)
    if output_summary["outputs"]:
        score += 10 if output_summary["existing"] else 5
        if output_summary["hashed"]:
            score += 10
        reasons.append("declared outputs recorded")
    data_total = int(data_availability.get("total", 0) or 0)
    if data_total and int(data_availability.get("missing", 0) or 0) == 0:
        score += 10
        reasons.append("declared data paths are present")
    if any(item.get("metadata_status") == "versioned" for item in model_artifacts):
        score += 5
        reasons.append("model artifact version metadata found")
    score = min(100, score)
    if score >= 85:
        label = "strong"
    elif score >= 60:
        label = "usable"
    elif score >= 35:
        label = "partial"
    else:
        label = "weak"
    gaps: list[str] = []
    if not manifest:
        gaps.append("Run the workflow once to produce an automation manifest.")
    if int(data_availability.get("missing", 0) or 0):
        gaps.append("Resolve missing declared input/output paths.")
    if not any(item.get("metadata_status") == "versioned" for item in model_artifacts):
        gaps.append("Add sidecar metadata for model artifacts: library versions, feature schema, and input dimensions.")
    return {"score": score, "label": label, "reasons": reasons, "gaps": gaps, "output_summary": output_summary}


def _stage_engine(stage: Mapping[str, Any]) -> str:
    for key in ("R", "engine", "runtime_engine"):
        value = _clean_text(stage.get(key))
        if value:
            return value
    return "runpy"


def _output_rows_by_stage(data_availability: Mapping[str, Any]) -> dict[int, list[Mapping[str, Any]]]:
    rows_by_stage: dict[int, list[Mapping[str, Any]]] = {}
    for row in data_availability.get("rows", []):
        if not isinstance(row, Mapping) or row.get("kind") != "output":
            continue
        try:
            stage_number = int(row.get("stage", 0) or 0)
        except (TypeError, ValueError):
            continue
        if stage_number:
            rows_by_stage.setdefault(stage_number, []).append(row)
    return rows_by_stage


def _input_rows_by_stage(data_availability: Mapping[str, Any]) -> dict[int, list[Mapping[str, Any]]]:
    rows_by_stage: dict[int, list[Mapping[str, Any]]] = {}
    for row in data_availability.get("rows", []):
        if not isinstance(row, Mapping) or row.get("kind") != "input":
            continue
        try:
            stage_number = int(row.get("stage", 0) or 0)
        except (TypeError, ValueError):
            continue
        if stage_number:
            rows_by_stage.setdefault(stage_number, []).append(row)
    return rows_by_stage


def _manifest_stage_statuses(manifest: Mapping[str, Any] | None) -> dict[int, str]:
    statuses: dict[int, str] = {}
    if not manifest:
        return statuses
    raw_stages = manifest.get("stages") or manifest.get("stage_results") or []
    if not isinstance(raw_stages, list):
        return statuses
    for entry in raw_stages:
        if not isinstance(entry, Mapping):
            continue
        raw_stage = entry.get("stage") or entry.get("stage_index") or entry.get("index")
        try:
            stage_number = int(raw_stage)
        except (TypeError, ValueError):
            continue
        if stage_number <= 0:
            stage_number += 1
        status = _clean_text(entry.get("status") or entry.get("state") or entry.get("result"))
        if status:
            statuses[stage_number] = status
    return statuses


def _artifact_mtime(row: Mapping[str, Any]) -> float | None:
    raw_path = _clean_text(row.get("resolved_path"))
    if not raw_path:
        return None
    try:
        return Path(raw_path).stat().st_mtime
    except OSError:
        return None


def _stage_is_stale(
    stage_number: int,
    inputs_by_stage: Mapping[int, Sequence[Mapping[str, Any]]],
    outputs_by_stage: Mapping[int, Sequence[Mapping[str, Any]]],
) -> bool:
    input_times = [_artifact_mtime(row) for row in inputs_by_stage.get(stage_number, [])]
    output_times = [_artifact_mtime(row) for row in outputs_by_stage.get(stage_number, [])]
    input_times = [value for value in input_times if value is not None]
    output_times = [value for value in output_times if value is not None]
    return bool(input_times and output_times and max(input_times) > min(output_times))


def _model_version_issues(
    model_artifacts: Sequence[Mapping[str, Any]],
    *,
    current_versions: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    current_versions = current_versions or {}
    version_key_map = {
        "sklearn_version": "sklearn_version",
        "scikit_learn_version": "sklearn_version",
        "torch_version": "torch_version",
        "stable_baselines3_version": "stable_baselines3_version",
        "mlflow_version": "mlflow_version",
    }
    issues: list[dict[str, Any]] = []
    for artifact in model_artifacts:
        metadata = artifact.get("metadata")
        metadata_map = metadata if isinstance(metadata, Mapping) else {}
        artifact_path = _clean_text(artifact.get("path") or artifact.get("name"))
        if artifact.get("metadata_status") != "versioned":
            issues.append(
                {
                    "severity": "warning",
                    "path": artifact_path,
                    "issue": "missing model metadata",
                    "recommendation": "Add sidecar metadata with library versions, feature schema, and input dimensions.",
                }
            )
            continue
        for metadata_key, current_key in version_key_map.items():
            recorded = _clean_text(metadata_map.get(metadata_key))
            current = _clean_text(current_versions.get(current_key))
            if recorded and current and recorded != current:
                issues.append(
                    {
                        "severity": "blocker",
                        "path": artifact_path,
                        "issue": f"{metadata_key} mismatch",
                        "recorded": recorded,
                        "current": current,
                        "recommendation": "Retrain/re-export the model or run with a compatible environment before executing dependent stages.",
                    }
                )
        if not any(key in metadata_map for key in ("feature_schema", "features", "input_dim", "n_features_in_", "observation_shape")):
            issues.append(
                {
                    "severity": "warning",
                    "path": artifact_path,
                    "issue": "missing feature shape/schema metadata",
                    "recommendation": "Record feature schema or input dimensions to prevent tensor-shape regressions.",
                }
            )
    return issues


def _installed_package_version(package_name: str) -> str:
    try:
        return package_version(package_name)
    except PackageNotFoundError:
        return ""


def _current_model_library_versions() -> dict[str, str]:
    candidates = {
        "sklearn_version": "scikit-learn",
        "torch_version": "torch",
        "stable_baselines3_version": "stable-baselines3",
        "mlflow_version": "mlflow",
    }
    versions: dict[str, str] = {}
    for key, package_name in candidates.items():
        installed = _installed_package_version(package_name)
        if installed:
            versions[key] = installed
    return versions


def build_autopilot_preflight(
    *,
    stages: Sequence[Mapping[str, Any]],
    sequence: Sequence[int],
    quality: Mapping[str, Any],
    data_availability: Mapping[str, Any],
    model_artifacts: Sequence[Mapping[str, Any]],
    manifest: Mapping[str, Any] | None = None,
    current_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Build a deterministic preflight plan for running the selected workflow."""

    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    actions: list[dict[str, Any]] = []
    stage_plan: list[dict[str, Any]] = []
    missing_inputs = data_availability.get("missing_inputs", [])
    missing_outputs = data_availability.get("missing_outputs", [])
    outputs_by_stage = _output_rows_by_stage(data_availability)
    inputs_by_stage = _input_rows_by_stage(data_availability)
    manifest_statuses = _manifest_stage_statuses(manifest)

    if quality.get("dependency_error"):
        blockers.append(
            {
                "kind": "dependency",
                "stage": "",
                "reason": str(quality.get("dependency_error") or "Invalid workflow dependencies."),
                "action": "Fix dependency ids or cycles before running.",
            }
        )
    for row in missing_inputs if isinstance(missing_inputs, list) else []:
        if not isinstance(row, Mapping):
            continue
        blockers.append(
            {
                "kind": "missing-input",
                "stage": row.get("stage", ""),
                "reason": f"Input `{row.get('path', '')}` is missing.",
                "action": "Generate the upstream stage, select an existing artifact, or fix the configured path.",
            }
        )
    for issue in _model_version_issues(model_artifacts, current_versions=current_versions):
        target = blockers if issue.get("severity") == "blocker" else warnings
        target.append({"kind": "model-compatibility", **issue})

    for idx in sequence:
        if not 0 <= int(idx) < len(stages):
            continue
        stage_number = int(idx) + 1
        stage = stages[int(idx)]
        output_rows = list(outputs_by_stage.get(stage_number, []))
        input_rows = list(inputs_by_stage.get(stage_number, []))
        missing_input_count = sum(1 for row in input_rows if row.get("status") == "missing")
        present_output_count = sum(1 for row in output_rows if row.get("status") == "present")
        missing_output_count = sum(1 for row in output_rows if row.get("status") == "missing")
        stale = _stage_is_stale(stage_number, inputs_by_stage, outputs_by_stage)
        engine = _stage_engine(stage)
        manifest_status = manifest_statuses.get(stage_number, "")
        if missing_input_count:
            decision = "blocked"
            reason = f"{missing_input_count} input artifact(s) missing"
            action = "generate-upstream"
        elif output_rows and present_output_count == len(output_rows) and not stale:
            decision = "skip"
            reason = "declared outputs are already present"
            action = "reuse-latest-valid-artifact"
        elif stale:
            decision = "run"
            reason = "inputs are newer than declared outputs"
            action = "rerun-stale-stage"
        elif missing_output_count:
            decision = "run"
            reason = f"{missing_output_count} declared output artifact(s) missing"
            action = "run-stage"
        else:
            decision = "run"
            reason = "no reusable output evidence found"
            action = "run-stage"
        if engine == "runpy" and decision == "run" and len(sequence) > 1:
            warnings.append(
                {
                    "kind": "runtime",
                    "stage": stage_number,
                    "reason": "runpy stage executes in-process and may serialize an otherwise parallel wave.",
                    "action": "Use agi.run for subprocess-backed parallel execution when appropriate.",
                }
            )
        stage_plan.append(
            {
                "stage": stage_number,
                "engine": engine,
                "decision": decision,
                "reason": reason,
                "autopilot_action": action,
                "manifest_status": manifest_status,
                "outputs_present": present_output_count,
                "outputs_missing": missing_output_count,
            }
        )
        actions.append(
            {
                "stage": stage_number,
                "action": action,
                "decision": decision,
                "reason": reason,
            }
        )

    runnable_stages = [row["stage"] for row in stage_plan if row["decision"] == "run"]
    skipped_stages = [row["stage"] for row in stage_plan if row["decision"] == "skip"]
    blocked_stages = [row["stage"] for row in stage_plan if row["decision"] == "blocked"]
    ready = not blockers and not blocked_stages
    if blockers:
        status = "blocked"
    elif runnable_stages:
        status = "ready"
    else:
        status = "cached"
    fastest_plan = {
        "critical_steps": int(quality.get("critical_steps", 0) or 0),
        "parallel_width": int(quality.get("parallel_width", 0) or 0),
        "runnable_stages": runnable_stages,
        "skipped_stages": skipped_stages,
        "blocked_stages": blocked_stages,
        "expected_outputs": [
            row
            for row in data_availability.get("rows", [])
            if isinstance(row, Mapping) and row.get("kind") == "output"
        ],
        "estimated_duration": "unknown",
    }
    return {
        "schema": PIPELINE_AUTOPILOT_PREFLIGHT_SCHEMA,
        "status": status,
        "ready": ready,
        "summary": {
            "stage_count": len(stage_plan),
            "runnable": len(runnable_stages),
            "skipped": len(skipped_stages),
            "blocked": len(blocked_stages),
            "warnings": len(warnings),
            "blockers": max(len(blockers), len(blocked_stages)),
        },
        "blockers": blockers,
        "warnings": warnings,
        "actions": actions,
        "stage_plan": stage_plan,
        "fastest_plan": fastest_plan,
        "missing_outputs": missing_outputs,
    }


def _load_json(path: Path) -> Mapping[str, Any] | None:
    try:
        if path.stat().st_size > 512 * 1024:
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, RuntimeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def _version_fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "sklearn_version",
        "scikit_learn_version",
        "torch_version",
        "stable_baselines3_version",
        "mlflow_version",
        "feature_schema",
        "features",
        "input_dim",
        "n_features_in_",
        "observation_shape",
    )
    return {key: payload[key] for key in keys if key in payload}


def _iter_files_limited(root: Path, *, max_depth: int) -> Iterable[Path]:
    if root.is_file():
        yield root
        return
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            children = sorted(current.iterdir(), key=lambda item: item.name)
        except OSError:
            continue
        for child in children:
            if child.is_file():
                yield child
            elif depth < max_depth and child.is_dir() and not child.name.startswith("."):
                stack.append((child, depth + 1))


def discover_model_artifacts(roots: Sequence[Path], *, max_files: int = 80, max_depth: int = 4) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for root in roots:
        try:
            if not root.exists():
                continue
        except OSError:
            continue
        for artifact in _iter_files_limited(root, max_depth=max_depth):
            if artifact.suffix.lower() not in _MODEL_SUFFIXES:
                continue
            text = str(artifact)
            if text in seen:
                continue
            seen.add(text)
            metadata: dict[str, Any] = {}
            for sidecar in (
                artifact.with_suffix(artifact.suffix + ".json"),
                artifact.with_suffix(".json"),
                artifact.parent / f"{artifact.stem}_metadata.json",
                artifact.parent / f"{artifact.stem}.metadata.json",
            ):
                payload = _load_json(sidecar)
                if payload:
                    metadata = _version_fields(payload)
                    break
            rows.append(
                {
                    "path": text,
                    "name": artifact.name,
                    "suffix": artifact.suffix.lower(),
                    "metadata_status": "versioned" if metadata else "missing",
                    "metadata": metadata,
                }
            )
            if len(rows) >= max_files:
                return rows
    return rows


def audit_pandas_compat(paths: Sequence[Path], *, max_findings: int = 100) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    for root in paths:
        if not root.exists():
            continue
        candidates = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in candidates:
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue
            for number, line in enumerate(lines, start=1):
                if not any(token in line for token in ("pandas", "pd.", "inplace", "][", ".append", "copy_on_write")):
                    continue
                for kind, pattern in _PANDAS_PATTERNS:
                    if kind == "chained-assignment" and not re.search(
                        r"\b(df|dataframe|frame)\b|\.loc\b|\.iloc\b",
                        line,
                        flags=re.IGNORECASE,
                    ):
                        continue
                    if pattern.search(line):
                        findings.append(
                            {
                                "path": str(path),
                                "line": number,
                                "kind": kind,
                                "text": line.strip(),
                            }
                        )
                        if len(findings) >= max_findings:
                            counts = Counter(item["kind"] for item in findings)
                            return {"total": len(findings), "by_kind": dict(counts), "findings": findings, "truncated": True}
    counts = Counter(item["kind"] for item in findings)
    return {"total": len(findings), "by_kind": dict(counts), "findings": findings, "truncated": False}


def build_workflow_cockpit_model(
    *,
    stages: Sequence[Mapping[str, Any]],
    sequence: Sequence[int],
    waves: Sequence[Sequence[int]],
    stage_ids: Mapping[int, str],
    stage_deps: Mapping[str, Sequence[str]],
    roots: Sequence[Path],
    input_roots: Sequence[Path] | None = None,
    manifest: Mapping[str, Any] | None = None,
    pandas_paths: Sequence[Path] = (),
    dependency_error: str | None = None,
    current_versions: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    quality = build_workflow_quality(
        stages,
        sequence,
        waves,
        stage_ids,
        stage_deps,
        dependency_error=dependency_error,
    )
    data_availability = build_data_availability(
        stages,
        sequence,
        roots,
        input_roots=input_roots,
    )
    model_artifacts = discover_model_artifacts(roots)
    pandas_compat = audit_pandas_compat(pandas_paths) if pandas_paths else {"total": 0, "by_kind": {}, "findings": [], "truncated": False}
    evidence = build_evidence_score(
        quality=quality,
        data_availability=data_availability,
        manifest=manifest,
        model_artifacts=model_artifacts,
    )
    autopilot = build_autopilot_preflight(
        stages=stages,
        sequence=sequence,
        quality=quality,
        data_availability=data_availability,
        model_artifacts=model_artifacts,
        manifest=manifest,
        current_versions=current_versions or _current_model_library_versions(),
    )
    return {
        "schema": PIPELINE_WORKFLOW_INSIGHTS_SCHEMA,
        "quality": quality,
        "data": data_availability,
        "models": model_artifacts,
        "pandas": pandas_compat,
        "evidence": evidence,
        "autopilot": autopilot,
    }
