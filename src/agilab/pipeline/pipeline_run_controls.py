from __future__ import annotations

import importlib.util
import hashlib
import json
import logging
import os
import socket
import subprocess
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

import pandas as pd
import re
import streamlit as st
from streamlit.errors import StreamlitAPIException

from agi_env import AgiEnv
from agi_env.snippet_contract import stale_snippet_cleanup_message
from agi_gui.pagelib import run_lab, save_csv

_import_guard_path = Path(__file__).resolve().parents[1] / "security" / "import_guard.py"
_import_guard_spec = importlib.util.spec_from_file_location("agilab_import_guard_local", _import_guard_path)
if _import_guard_spec is None or _import_guard_spec.loader is None:
    raise ModuleNotFoundError(f"Unable to load import_guard.py from {_import_guard_path}")
_import_guard_module = importlib.util.module_from_spec(_import_guard_spec)
_import_guard_spec.loader.exec_module(_import_guard_module)
import_agilab_module = _import_guard_module.import_agilab_module

_pipeline_stages = import_agilab_module(
    "agilab.pipeline_stages",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_stages.py",
    fallback_name="agilab_pipeline_stages_fallback",
)
_pipeline_runtime = import_agilab_module(
    "agilab.pipeline_runtime",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parent / "pipeline_runtime.py",
    fallback_name="agilab_pipeline_runtime_fallback",
)
_logging_utils = import_agilab_module(
    "agilab.logging_utils",
    current_file=__file__,
    fallback_path=Path(__file__).resolve().parents[1] / "environment/logging_utils.py",
    fallback_name="agilab_logging_utils_fallback",
)

logger = logging.getLogger(__name__)

PIPELINE_LOCK_SCHEMA = "agilab.pipeline.lock.v1"
PIPELINE_LOCK_FILENAME = "pipeline_run.lock"
PIPELINE_LOCK_DEFAULT_TTL_SEC = 6 * 3600.0
PIPELINE_RUN_LOG_MIN_LINES = 20
PIPELINE_RUN_LOG_LINE_HEIGHT_PX = 20
PIPELINE_RUN_LOG_HEIGHT = PIPELINE_RUN_LOG_MIN_LINES * PIPELINE_RUN_LOG_LINE_HEIGHT_PX
PIPELINE_AUTOMATION_SCHEMA = "agilab.pipeline.automation.v2"
PIPELINE_AUTOMATION_COMPATIBLE_SCHEMAS = ["agilab.pipeline.automation.v1"]
PIPELINE_AUTOMATION_PRODUCER = "agilab.pipeline.run_all_stages"
PIPELINE_SEQUENCE_METADATA_SCHEMA = "agilab.pipeline.sequence.v2"
PIPELINE_SEQUENCE_METADATA_COMPATIBLE_SCHEMAS = ["agilab.pipeline.sequence.v1"]
PIPELINE_AUTOMATION_MANIFEST_FILENAME = "pipeline_automation_manifest.json"
PIPELINE_AUTOMATION_OUTPUT_HASH_MAX_BYTES = 16 * 1024 * 1024
PIPELINE_AUTOMATION_PROFILES = ("balanced", "smoke", "fast", "evidence", "custom")
PIPELINE_AUTOMATION_PROFILE_LABELS = {
    "balanced": "Balanced",
    "smoke": "Smoke",
    "fast": "Fast",
    "evidence": "Evidence",
    "custom": "Custom",
}
PIPELINE_AUTOMATION_PROFILE_HELP = {
    "balanced": "Use the stage values saved in the workflow.",
    "smoke": "Use optional project-declared smoke overrides for the shortest validation run.",
    "fast": "Use optional project-declared fast overrides for quick iteration.",
    "evidence": "Use optional project-declared evidence overrides for fuller reproducible runs.",
    "custom": "Use saved stage values plus any project-declared custom overrides.",
}


def _pipeline_automation_producer_version() -> str:
    try:
        return package_version("agilab")
    except PackageNotFoundError:
        return ""


def _utc_timestamp() -> str:
    # Use a timezone-aware UTC clock (datetime.utcnow() is deprecated) while
    # preserving the historic naive "...Z" string format consumed downstream.
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z"


def _safe_file_sha256(path: Path) -> str:
    try:
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except (OSError, RuntimeError, ValueError):
        pass
    return ""


def _stable_json_sha256(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _normalize_pipeline_profile(profile: str | None) -> str:
    normalized = str(profile or "balanced").strip().lower()
    return normalized if normalized in PIPELINE_AUTOMATION_PROFILES else "balanced"


def _mapping_payload(raw: Any) -> Dict[str, Any]:
    return dict(raw) if isinstance(raw, Mapping) else {}


def _deep_merge_mapping(base: Mapping[str, Any], override: Mapping[str, Any]) -> Dict[str, Any]:
    merged: Dict[str, Any] = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = _deep_merge_mapping(current, value)
        else:
            merged[key] = value
    return merged


def _stage_profile_override(entry: Mapping[str, Any], profile: str) -> Dict[str, Any]:
    for key in ("profiles", "pipeline_profiles", "automation_profiles"):
        profile_map = entry.get(key)
        if not isinstance(profile_map, Mapping):
            continue
        override = profile_map.get(profile)
        if isinstance(override, Mapping):
            return dict(override)
    return {}


def _apply_stage_profile(entry: Mapping[str, Any], profile: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    base = dict(entry)
    override = _stage_profile_override(base, profile)
    if not override:
        return base, {}
    merged = _deep_merge_mapping(base, override)
    return merged, override


def _stage_automation(entry: Mapping[str, Any]) -> Dict[str, Any]:
    automation = _mapping_payload(entry.get("automation"))
    for key in ("skip_if_outputs_exist", "skip_if_outputs_current", "outputs", "output_paths", "inputs", "input_paths"):
        if key in entry and key not in automation:
            automation[key] = entry[key]
    return automation


def _iter_path_specs(value: Any) -> List[str]:
    if value is None or isinstance(value, bool):
        return []
    if isinstance(value, Path):
        return [str(value)]
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Mapping):
        paths: List[str] = []
        for key in sorted(value, key=str):
            paths.extend(_iter_path_specs(value[key]))
        return paths
    if isinstance(value, (list, tuple)):
        paths = []
        for item in value:
            paths.extend(_iter_path_specs(item))
        return paths
    if isinstance(value, set):
        paths = []
        for item in sorted(value, key=str):
            paths.extend(_iter_path_specs(item))
        return paths
    return [str(value)] if str(value).strip() else []


def _truthy_pipeline_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _workflow_data_root(env: AgiEnv, stages_file: Path) -> Path:
    for method_name in ("workflow_data_root_path", "share_root_path"):
        method = getattr(env, method_name, None)
        if callable(method):
            try:
                return Path(method()).expanduser().resolve(strict=False)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
    for attr_name in ("agi_share_path_abs", "share_root", "root", "data_root"):
        raw = getattr(env, attr_name, None)
        if raw:
            try:
                return Path(raw).expanduser().resolve(strict=False)
            except (OSError, RuntimeError, TypeError, ValueError):
                pass
    return stages_file.parent.expanduser().resolve(strict=False)


def _resolve_stage_output_path(spec: Any, *, env: AgiEnv, stages_file: Path) -> Optional[Path]:
    normalized = _normalize_output_path_spec(spec)
    if not normalized:
        return None
    candidate = Path(normalized).expanduser()
    if candidate.is_absolute():
        return candidate.resolve(strict=False)
    return (_workflow_data_root(env, stages_file) / candidate).resolve(strict=False)


def _stage_output_specs(entry: Mapping[str, Any]) -> List[str]:
    automation = _stage_automation(entry)
    specs: List[str] = []
    for key in ("outputs", "output_paths"):
        for item in _iter_path_specs(automation.get(key)):
            normalized = _normalize_output_path_spec(item)
            if normalized:
                specs.append(normalized)
    return sorted(set(specs))


def _stage_output_skip_rule(entry: Mapping[str, Any]) -> Dict[str, Any]:
    automation = _stage_automation(entry)
    enabled = _truthy_pipeline_flag(
        automation.get("skip_if_outputs_exist", automation.get("skip_if_outputs_current"))
    )
    return {
        "enabled": enabled,
        "outputs": _stage_output_specs(entry),
    }


def _stage_output_records(
    entry: Mapping[str, Any],
    *,
    env: AgiEnv,
    stages_file: Path,
) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for spec in _stage_output_specs(entry):
        path = _resolve_stage_output_path(spec, env=env, stages_file=stages_file)
        if path is None:
            continue
        exists = path.exists()
        is_dir = path.is_dir() if exists else False
        is_file = path.is_file() if exists else False
        size_bytes: Optional[int] = None
        mtime: Optional[float] = None
        sha256 = ""
        sha256_status = "missing"
        if exists:
            try:
                stat = path.stat()
                size_bytes = int(stat.st_size)
                mtime = float(stat.st_mtime)
                if is_file and size_bytes <= PIPELINE_AUTOMATION_OUTPUT_HASH_MAX_BYTES:
                    sha256 = _safe_file_sha256(path)
                    sha256_status = "ok" if sha256 else "error"
                elif is_file:
                    sha256_status = "too_large"
                elif is_dir:
                    sha256_status = "directory"
                else:
                    sha256_status = "not_regular_file"
            except OSError:
                size_bytes = None
                mtime = None
                sha256_status = "stat_error"
        records.append(
            {
                "spec": spec,
                "path": str(path),
                "exists": exists,
                "is_dir": is_dir,
                "is_file": is_file,
                "size_bytes": size_bytes,
                "mtime": mtime,
                "sha256": sha256,
                "sha256_status": sha256_status,
            }
        )
    return records


def _automation_manifest_output_rows(manifest: Mapping[str, Any]) -> List[Dict[str, Any]]:
    output_rows: List[Dict[str, Any]] = []
    for stage_record in manifest.get("stages", []):
        if not isinstance(stage_record, Mapping):
            continue
        for output_record in stage_record.get("outputs", []):
            if not isinstance(output_record, Mapping):
                continue
            output_rows.append(
                {
                    "stage": stage_record.get("stage_index", ""),
                    "status": stage_record.get("status", ""),
                    "spec": output_record.get("spec", ""),
                    "exists": bool(output_record.get("exists")),
                    "kind": (
                        "file"
                        if output_record.get("is_file")
                        else "directory"
                        if output_record.get("is_dir")
                        else "other"
                    ),
                    "size_bytes": output_record.get("size_bytes"),
                    "sha256_status": output_record.get("sha256_status", ""),
                    "sha256": output_record.get("sha256", ""),
                    "path": output_record.get("path", ""),
                }
            )
    return output_rows


def _automation_manifest_output_summary(manifest: Mapping[str, Any]) -> Dict[str, int]:
    output_rows = _automation_manifest_output_rows(manifest)
    return {
        "outputs": len(output_rows),
        "existing": sum(1 for record in output_rows if record.get("exists")),
        "hashed": sum(1 for record in output_rows if record.get("sha256_status") == "ok"),
        "too_large": sum(1 for record in output_rows if record.get("sha256_status") == "too_large"),
        "missing": sum(1 for record in output_rows if not record.get("exists")),
    }


def _automation_manifest_stage_summary(manifest: Mapping[str, Any]) -> Dict[str, int]:
    summary = manifest.get("summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    return {
        "stage_count": int(summary.get("stage_count", 0) or 0),
        "executed": int(summary.get("executed", 0) or 0),
        "skipped": int(summary.get("skipped", 0) or 0),
        "failed": int(summary.get("failed", 0) or 0),
    }


def _automation_manifest_schema_caption(manifest: Mapping[str, Any]) -> str:
    schema = str(manifest.get("schema", "") or "unknown")
    compatible_schemas = manifest.get("compatible_schemas", [])
    compatible_schema_text = ""
    if isinstance(compatible_schemas, list):
        compatible_schema_text = ", ".join(str(item) for item in compatible_schemas if item)
    schema_status = _automation_manifest_schema_status(manifest)
    if compatible_schema_text:
        return (
            f"Manifest schema: {schema} "
            f"({schema_status}; compatible readers: {compatible_schema_text})"
        )
    return f"Manifest schema: {schema} ({schema_status})"


def _automation_manifest_schema_status(manifest: Mapping[str, Any]) -> str:
    schema = str(manifest.get("schema", "") or "").strip()
    if schema == PIPELINE_AUTOMATION_SCHEMA:
        return "current"
    if schema in PIPELINE_AUTOMATION_COMPATIBLE_SCHEMAS:
        return "compatible legacy"
    if not schema:
        return "unknown"
    return "unsupported"


def _automation_manifest_paths(
    manifest: Mapping[str, Any],
    *,
    path: str = "",
) -> tuple[str, str]:
    run_manifest_path = str(
        manifest.get("run_manifest_path", "") or manifest.get("manifest_path", "") or ""
    ).strip()
    latest_manifest_path = str(
        manifest.get("latest_manifest_path", "") or path or ""
    ).strip()
    return run_manifest_path, latest_manifest_path


def _automation_manifest_identity_captions(
    manifest: Mapping[str, Any],
    *,
    path: str = "",
) -> List[str]:
    producer = str(manifest.get("producer", "") or "").strip()
    run_id = str(manifest.get("run_id", "") or "").strip()
    profile = str(manifest.get("profile", "") or "").strip()
    max_workers = str(manifest.get("max_workers", "") or "").strip()
    workflow_source = str(manifest.get("workflow_source", "") or "").strip()
    app = str(manifest.get("app", "") or "").strip()
    target = str(manifest.get("target", "") or "").strip()
    lab_dir = str(manifest.get("lab_dir", "") or "").strip()
    stages_file = str(manifest.get("stages_file", "") or "").strip()
    stages_file_sha256 = str(manifest.get("stages_file_sha256", "") or "").strip()
    started_at = str(manifest.get("started_at", "") or "").strip()
    finished_at = str(manifest.get("finished_at", "") or "").strip()
    run_manifest_path, latest_manifest_path = _automation_manifest_paths(
        manifest,
        path=path,
    )
    displayed_manifest_path = run_manifest_path or latest_manifest_path
    manifest_sha256 = str(manifest.get("manifest_sha256", "") or "").strip()
    captions: List[str] = []
    if producer:
        captions.append(f"Manifest producer: {producer}")
    producer_version = str(manifest.get("producer_version", "") or "").strip()
    if producer_version:
        captions.append(f"Producer version: {producer_version}")
    if run_id:
        captions.append(f"Run ID: {run_id}")
    if profile:
        captions.append(f"Automation profile: {profile}")
    if max_workers:
        captions.append(f"Max workers: {max_workers}")
    if "local_only" in manifest:
        captions.append(f"Local-only evidence: {'yes' if manifest.get('local_only') else 'no'}")
    if workflow_source:
        captions.append(f"Workflow source: {workflow_source}")
    if app:
        captions.append(f"App: {app}")
    if target:
        captions.append(f"Target: {target}")
    if lab_dir:
        captions.append(f"Lab directory: {lab_dir}")
    if stages_file:
        captions.append(f"Stages file: {stages_file}")
    if stages_file_sha256:
        captions.append(f"Stages file SHA-256: {stages_file_sha256}")
    if started_at:
        captions.append(f"Started at: {started_at}")
    if finished_at:
        captions.append(f"Finished at: {finished_at}")
    if run_manifest_path:
        captions.append(f"Run manifest file: {run_manifest_path}")
    elif displayed_manifest_path:
        captions.append(f"Manifest file: {displayed_manifest_path}")
    if (
        latest_manifest_path
        and run_manifest_path
        and latest_manifest_path != run_manifest_path
    ):
        captions.append(f"Latest manifest file: {latest_manifest_path}")
    if manifest_sha256:
        captions.append(f"Manifest SHA-256: {manifest_sha256}")
    return captions


def _automation_manifest_duration_label(manifest: Mapping[str, Any]) -> str:
    duration_value = manifest.get("duration_seconds")
    try:
        duration_seconds = float(duration_value)
    except (TypeError, ValueError):
        return "unknown"
    if duration_seconds < 0:
        return "unknown"
    if duration_seconds < 60:
        return f"{duration_seconds:.1f}s"
    minutes, seconds = divmod(duration_seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {seconds:.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes}m {seconds:.1f}s"


def _automation_manifest_error_caption(manifest: Mapping[str, Any]) -> str:
    error = str(manifest.get("error", "") or "").strip()
    if not error:
        return ""
    return f"Run error: {error}"


def _should_skip_current_outputs(
    entry: Mapping[str, Any],
    *,
    env: AgiEnv,
    stages_file: Path,
) -> tuple[bool, List[Dict[str, Any]]]:
    rule = _stage_output_skip_rule(entry)
    output_records = _stage_output_records(entry, env=env, stages_file=stages_file)
    if not rule["enabled"] or not output_records:
        return False, output_records
    return all(record["exists"] for record in output_records), output_records


def _stage_disabled(entry: Mapping[str, Any]) -> bool:
    automation = _stage_automation(entry)
    if entry.get("enabled") is False or automation.get("enabled") is False:
        return True
    return bool(entry.get("skip") is True or automation.get("skip") is True)


def _stage_id(entry: Mapping[str, Any], idx: int) -> str:
    raw = str(entry.get("id") or entry.get("stage_id") or "").strip()
    if raw:
        return raw
    return f"stage_{idx + 1}"


def _stage_deps(entry: Mapping[str, Any]) -> List[str]:
    raw = entry.get("deps", entry.get("depends_on", entry.get("dependencies", [])))
    if isinstance(raw, str):
        return [raw] if raw.strip() else []
    if isinstance(raw, (list, tuple)):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _normalize_dependency_path(raw: Any) -> str:
    text = str(raw or "").strip().strip("\"'")
    if not text or "://" in text or text.startswith("$"):
        return ""
    text = text.replace("\\", "/")
    for marker in (
        "/localshare/agi/",
        "/clustershare/",
        "/share/agi/",
    ):
        if marker in text:
            text = text.split(marker, 1)[1]
            break
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _normalize_output_path_spec(raw: Any) -> str:
    text = str(raw or "").strip().strip("\"'")
    if not text or "://" in text or text.startswith("$"):
        return ""
    text = text.replace("\\", "/")
    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return str(candidate)
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def _literal_stage_paths(entry: Mapping[str, Any]) -> List[str]:
    paths: List[str] = []
    for key, value in entry.items():
        key_text = str(key).lower()
        if key_text in {"c", "q", "m", "r", "id", "deps", "depends_on", "dependencies"}:
            continue
        if any(token in key_text for token in ("path", "dir", "data", "glob", "input", "output", "file")):
            for item in _iter_path_specs(value):
                normalized = _normalize_dependency_path(item)
                if normalized:
                    paths.append(normalized)
    code = str(entry.get("C", "") or "")
    for _quote, literal in re.findall(r"(['\"])([^'\"]+/[^'\"]*)\1", code):
        normalized = _normalize_dependency_path(literal)
        if normalized:
            paths.append(normalized)
    return sorted(set(paths))


def _stage_declared_outputs(entry: Mapping[str, Any]) -> List[str]:
    outputs: List[str] = []
    d_value = _normalize_dependency_path(entry.get("D", ""))
    if d_value and not d_value.endswith("/install"):
        outputs.append(d_value)
    automation = _stage_automation(entry)
    for item in _iter_path_specs(automation.get("outputs", automation.get("output_paths", []))):
        normalized = _normalize_dependency_path(item)
        if normalized:
            outputs.append(normalized)
    code = str(entry.get("C", "") or "")
    for pattern in (
        r"\bdata_out\s*=\s*(['\"])(?P<path>[^'\"]+)\1",
        r"['\"]data_out['\"]\s*:\s*(['\"])(?P<path>[^'\"]+)\1",
        r"\boutput_dir\s*=\s*(['\"])(?P<path>[^'\"]+)\1",
        r"['\"]output_dir['\"]\s*:\s*(['\"])(?P<path>[^'\"]+)\1",
    ):
        for match in re.finditer(pattern, code):
            normalized = _normalize_dependency_path(match.group("path"))
            if normalized:
                outputs.append(normalized)
    return sorted(set(outputs))


def _path_depends_on_output(path: str, output: str) -> bool:
    if not path or not output or path == output:
        return path == output
    return path.startswith(output.rstrip("/") + "/") or path.startswith(output.rstrip("/") + "*")


def infer_stage_dependency_suggestions(
    stages: List[Dict[str, Any]],
    sequence: List[int],
    profile: str = "balanced",
) -> Dict[str, List[str]]:
    """Infer conservative stage dependency suggestions from explicit ids and path literals."""
    entries: Dict[int, Dict[str, Any]] = {}
    ids_by_idx: Dict[int, str] = {}
    outputs_by_idx: Dict[int, List[str]] = {}
    paths_by_idx: Dict[int, List[str]] = {}
    for idx in sequence:
        if not 0 <= idx < len(stages):
            continue
        entry, _override = _apply_stage_profile(stages[idx], profile)
        entries[idx] = entry
        ids_by_idx[idx] = _stage_id(entry, idx)
        outputs_by_idx[idx] = _stage_declared_outputs(entry)
        paths_by_idx[idx] = _literal_stage_paths(entry)

    suggestions: Dict[str, List[str]] = {stage_id: [] for stage_id in ids_by_idx.values()}
    for consumer_idx, consumer_entry in entries.items():
        consumer_id = ids_by_idx[consumer_idx]
        consumer_d = _normalize_dependency_path(consumer_entry.get("D", ""))
        consumer_paths = paths_by_idx.get(consumer_idx, [])
        deps: List[str] = []
        for producer_idx, producer_entry in entries.items():
            if producer_idx == consumer_idx:
                continue
            producer_id = ids_by_idx[producer_idx]
            producer_d = _normalize_dependency_path(producer_entry.get("D", ""))
            if producer_d.endswith("/install") and consumer_d.startswith(producer_d.removesuffix("/install") + "/"):
                deps.append(producer_id)
                continue
            for output in outputs_by_idx.get(producer_idx, []):
                if any(_path_depends_on_output(path, output) for path in consumer_paths):
                    deps.append(producer_id)
                    break
        suggestions[consumer_id] = sorted(set(deps), key=deps.index)
    return suggestions


def _build_stage_waves(
    stages: List[Dict[str, Any]],
    sequence: List[int],
    profile: str,
    dependency_overrides: Mapping[str, List[str]] | None = None,
) -> tuple[List[List[int]], Optional[str], Dict[int, str], Dict[int, List[str]]]:
    dependency_overrides = dependency_overrides or {}
    entries_by_idx: Dict[int, Dict[str, Any]] = {}
    ids_by_idx: Dict[int, str] = {}
    deps_by_idx: Dict[int, List[str]] = {}
    explicit_deps = False
    seen_ids: Dict[str, int] = {}
    for idx in sequence:
        if not 0 <= idx < len(stages):
            continue
        entry, _override = _apply_stage_profile(stages[idx], profile)
        entries_by_idx[idx] = entry
        stage_id = _stage_id(entry, idx)
        if stage_id in seen_ids:
            return [], f"Duplicate workflow stage id `{stage_id}` on stages {seen_ids[stage_id] + 1} and {idx + 1}.", ids_by_idx, deps_by_idx
        seen_ids[stage_id] = idx
        ids_by_idx[idx] = stage_id
        deps = _stage_deps(entry)
        if stage_id in dependency_overrides:
            deps = [str(dep).strip() for dep in dependency_overrides.get(stage_id, []) if str(dep).strip()]
        explicit_deps = explicit_deps or bool(deps)
        deps_by_idx[idx] = deps
    if not explicit_deps:
        return [[idx] for idx in sequence], None, ids_by_idx, deps_by_idx

    selected_ids = set(ids_by_idx.values())
    for idx, deps in deps_by_idx.items():
        for dep in deps:
            if dep not in seen_ids:
                return [], f"Stage {idx + 1} depends on unknown stage id `{dep}`.", ids_by_idx, deps_by_idx
            if dep not in selected_ids:
                return [], f"Stage {idx + 1} depends on `{dep}`, which is outside the selected execution sequence.", ids_by_idx, deps_by_idx

    completed: set[str] = set()
    remaining = list(sequence)
    waves: List[List[int]] = []
    while remaining:
        ready = [
            idx
            for idx in remaining
            if all(dep in completed for dep in deps_by_idx.get(idx, []))
        ]
        if not ready:
            cycle_ids = ", ".join(ids_by_idx.get(idx, f"stage_{idx + 1}") for idx in remaining)
            return [], f"Workflow stage dependencies contain a cycle or unresolved chain: {cycle_ids}.", ids_by_idx, deps_by_idx
        waves.append(ready)
        for idx in ready:
            remaining.remove(idx)
            completed.add(ids_by_idx[idx])
    return waves, None, ids_by_idx, deps_by_idx


def _dot_escape(value: object) -> str:
    return str(value or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _pipeline_dependency_dot(
    *,
    stage_ids: Mapping[int, str],
    stage_deps: Mapping[int, List[str]],
    waves: List[List[int]],
) -> str:
    wave_by_idx: Dict[int, int] = {}
    for wave_number, wave in enumerate(waves, start=1):
        for idx in wave:
            wave_by_idx[int(idx)] = wave_number
    labels = {stage_id: f"{idx + 1}. {stage_id}\\nwave {wave_by_idx.get(idx, '?')}" for idx, stage_id in stage_ids.items()}
    lines = [
        "digraph workflow_dependencies {",
        "  graph [rankdir=LR, bgcolor=\"transparent\"];",
        "  node [shape=box, style=\"rounded,filled\", fillcolor=\"#F7FAFC\", color=\"#2D3748\"];",
        "  edge [color=\"#4A5568\"];",
    ]
    for stage_id, label in labels.items():
        lines.append(f'  "{_dot_escape(stage_id)}" [label="{_dot_escape(label)}"];')
    for idx, deps in stage_deps.items():
        stage_id = stage_ids.get(idx, f"stage_{idx + 1}")
        for dep_id in deps:
            if dep_id in labels:
                lines.append(f'  "{_dot_escape(dep_id)}" -> "{_dot_escape(stage_id)}";')
    for wave in waves:
        wave_stage_ids = [stage_ids[idx] for idx in wave if idx in stage_ids]
        if len(wave_stage_ids) > 1:
            same_rank = "; ".join(f'"{_dot_escape(stage_id)}"' for stage_id in wave_stage_ids)
            lines.append(f"  {{ rank=same; {same_rank}; }}")
    lines.append("}")
    return "\n".join(lines)


def _resolve_stage_engine_runtime(
    entry: Mapping[str, Any],
    *,
    env: AgiEnv,
    idx: int,
    selected_map: Mapping[int, str],
    engine_map: Mapping[int, str],
    default_runtime: str,
) -> tuple[str, str]:
    raw_runtime = _pipeline_stages.normalize_runtime_path(entry.get("E", ""))
    venv_path = raw_runtime if _pipeline_runtime.is_valid_runtime_root(raw_runtime) else ""
    runtime_root = venv_path or selected_map.get(idx, "") or default_runtime
    entry_engine = str(entry.get("R", "") or "")
    ui_engine = str(engine_map.get(idx) or "")
    if ui_engine and ui_engine != entry_engine:
        if entry_engine.startswith("agi.") and ui_engine == "runpy":
            engine = entry_engine
        else:
            engine = ui_engine
    elif entry_engine:
        engine = entry_engine
    else:
        engine = "agi.run" if runtime_root else "runpy"
    if runtime_root and engine == "runpy":
        engine = "agi.run"
    if engine.startswith("agi.") and not runtime_root:
        fallback_runtime = _pipeline_stages.normalize_runtime_path(
            getattr(env, "active_app", "") or ""
        )
        if _pipeline_runtime.is_valid_runtime_root(fallback_runtime):
            runtime_root = fallback_runtime
    return engine, runtime_root


def _stage_script_path(target_base: Path, idx: int) -> Path:
    return (target_base / f"AGI_run_stage{idx + 1}.py").resolve()


def _run_stage_subprocess(
    command: List[str],
    *,
    cwd: Path,
    extra_env: Mapping[str, str],
) -> str:
    env_vars = os.environ.copy()
    env_vars.update({str(key): str(value) for key, value in extra_env.items()})
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        env=env_vars,
        text=True,
        capture_output=True,
        check=False,
    )
    output = "\n".join(part for part in [completed.stdout, completed.stderr] if part)
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command exited with status {completed.returncode}: {' '.join(command)}\n{output.strip()}"
        )
    return output


def _parallel_agi_wave_eligible(
    stages: List[Dict[str, Any]],
    wave: List[int],
    *,
    profile: str,
    env: AgiEnv,
    stages_file: Path,
    selected_map: Mapping[int, str],
    engine_map: Mapping[int, str],
    default_runtime: str,
) -> bool:
    if len(wave) < 2:
        return False
    for idx in wave:
        entry, _override = _apply_stage_profile(stages[idx], profile)
        if _stage_disabled(entry):
            return False
        skip_current, _outputs = _should_skip_current_outputs(entry, env=env, stages_file=stages_file)
        if skip_current:
            return False
        code, _normalized = _normalize_legacy_agi_run_request_code(str(entry.get("C", "") or ""))
        candidate = {**entry, "C": code}
        if not _pipeline_stages.is_runnable_stage(candidate):
            return False
        engine, runtime_root = _resolve_stage_engine_runtime(
            candidate,
            env=env,
            idx=idx,
            selected_map=selected_map,
            engine_map=engine_map,
            default_runtime=default_runtime,
        )
        if not engine.startswith("agi.") or not runtime_root:
            return False
    return True


def _run_parallel_agi_wave(
    *,
    stages: List[Dict[str, Any]],
    wave: List[int],
    profile: str,
    env: AgiEnv,
    index_page: str,
    stages_file: Path,
    run_id: str,
    selected_map: Mapping[int, str],
    engine_map: Mapping[int, str],
    default_runtime: str,
    target_base: Path,
    max_workers: int,
    manifest_stage_records: List[Dict[str, Any]],
    log_placeholder: Optional[Any],
) -> int:
    prepared: List[Dict[str, Any]] = []
    base_stage_env: Dict[str, str] = {}
    for idx in wave:
        entry, profile_override = _apply_stage_profile(stages[idx], profile)
        code, normalized_agi_code = _normalize_legacy_agi_run_request_code(str(entry.get("C", "") or ""))
        if normalized_agi_code:
            entry = {**entry, "C": code}
            _push_run_log(
                index_page,
                (
                    f"Stage {idx + 1}: normalized legacy AGI RunRequest snippet "
                    "from StepRequest/steps to StageRequest/stages."
                ),
                log_placeholder,
            )
        engine, venv_root = _resolve_stage_engine_runtime(
            entry,
            env=env,
            idx=idx,
            selected_map=selected_map,
            engine_map=engine_map,
            default_runtime=default_runtime,
        )
        summary = _pipeline_stages.stage_summary({"Q": entry.get("Q", ""), "C": code})
        env_label = _pipeline_runtime.label_for_stage_runtime(
            venv_root,
            engine=engine,
            code=code,
        )
        script_path = _stage_script_path(target_base, idx)
        script_path.write_text(_pipeline_runtime.wrap_code_with_mlflow_resume(code), encoding="utf-8")
        python_cmd = _pipeline_runtime.python_for_stage(
            venv_root,
            engine=engine,
            code=code,
        )
        stage_env = dict(base_stage_env)
        stage_env.update(
            {
                "AGILAB_PIPELINE_PROFILE": profile,
                "AGILAB_PIPELINE_RUN_ID": run_id,
                "AGILAB_PIPELINE_STAGE_INDEX": str(idx + 1),
                "AGILAB_PIPELINE_MANIFEST": str(_pipeline_manifest_paths(env, index_page, run_id)[0]),
            }
        )
        stage_record: Dict[str, Any] = {
            "stage_index": idx + 1,
            "status": "running",
            "profile": profile,
            "profile_override_applied": bool(profile_override),
            "profile_override_keys": sorted(str(key) for key in profile_override),
            "output_skip_rule": _stage_output_skip_rule(entry),
            "description": str(entry.get("D", "") or ""),
            "summary": summary,
            "engine": engine,
            "runtime": venv_root or "",
            "code_sha256": hashlib.sha256(str(code or "").encode("utf-8")).hexdigest(),
            "started_at": _utc_timestamp(),
            "finished_at": "",
            "duration_seconds": None,
            "outputs": [],
            "error": "",
            "script_path": str(script_path),
            "parallel_wave": True,
            "mlflow_stage_run": "disabled_for_parallel_wave",
        }
        manifest_stage_records.append(stage_record)
        if profile_override:
            _push_run_log(
                index_page,
                f"Stage {idx + 1}: applied `{profile}` profile override.",
                log_placeholder,
            )
        _push_run_log(
            index_page,
            f"Stage {idx + 1}: parallel start engine={engine}, env={env_label}, summary='{summary}'",
            log_placeholder,
        )
        prepared.append(
            {
                "idx": idx,
                "record": stage_record,
                "entry": entry,
                "started": time.time(),
                "command": [str(python_cmd), str(script_path)],
                "stage_env": stage_env,
                "script_path": script_path,
            }
        )

    executed = 0
    first_error: Optional[BaseException] = None
    worker_count = max(1, min(int(max_workers or 1), len(prepared)))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {
            executor.submit(
                _run_stage_subprocess,
                item["command"],
                cwd=target_base,
                extra_env=item["stage_env"],
            ): item
            for item in prepared
        }
        for future in as_completed(futures):
            item = futures[future]
            idx = int(item["idx"])
            record = item["record"]
            try:
                output = future.result()
            except BaseException as exc:
                record["status"] = "failed"
                record["finished_at"] = _utc_timestamp()
                record["duration_seconds"] = max(time.time() - float(item["started"]), 0.0)
                record["error"] = str(exc)
                _push_run_log(index_page, f"Stage {idx + 1}: failed in parallel wave: {exc}", log_placeholder)
                if first_error is None:
                    first_error = exc
                continue
            preview = (output or "").strip()
            if preview:
                _push_run_log(index_page, f"Output (stage {idx + 1}):\n{preview}", log_placeholder)
            else:
                _push_run_log(index_page, f"Output (stage {idx + 1}): parallel {record['engine']} executed (no captured stdout)", log_placeholder)
            record["status"] = "completed"
            record["finished_at"] = _utc_timestamp()
            record["duration_seconds"] = max(time.time() - float(item["started"]), 0.0)
            record["outputs"] = _stage_output_records(item["entry"], env=env, stages_file=stages_file)
            executed += 1
    if first_error is not None:
        raise first_error
    return executed


def _pipeline_manifest_paths(
    env: AgiEnv,
    index_page: str,
    run_id: str,
) -> tuple[Path, Path]:
    log_file_path = st.session_state.get(f"{index_page}__run_log_file")
    if log_file_path:
        latest_path = Path(log_file_path).expanduser().parent / PIPELINE_AUTOMATION_MANIFEST_FILENAME
        run_path = Path(log_file_path).expanduser().with_suffix(".pipeline_manifest.json")
        return run_path, latest_path
    app_name = str(getattr(env, "app", "") or getattr(env, "target", "") or "agilab")
    log_dir_candidate = getattr(env, "runenv", None) or (Path.home() / "log" / "execute" / app_name)
    latest_path = Path(log_dir_candidate).expanduser() / PIPELINE_AUTOMATION_MANIFEST_FILENAME
    return latest_path.with_name(f"pipeline_automation_{run_id}.json"), latest_path


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(path.name + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp_path.replace(path)


def _write_pipeline_automation_manifest(
    *,
    env: AgiEnv,
    index_page: str,
    run_id: str,
    profile: str,
    status: str,
    lab_dir: Path,
    stages_file: Path,
    sequence: List[int],
    waves: List[List[int]],
    max_workers: int,
    stage_ids: Mapping[int, str],
    stage_deps: Mapping[int, List[str]],
    stages: List[Dict[str, Any]],
    started_at: str,
    finished_at: str,
    executed: int,
    skipped: int,
    error: str,
    duration_seconds: float | None = None,
) -> Optional[Path]:
    run_path, latest_path = _pipeline_manifest_paths(env, index_page, run_id)
    payload: Dict[str, Any] = {
        "schema": PIPELINE_AUTOMATION_SCHEMA,
        "compatible_schemas": PIPELINE_AUTOMATION_COMPATIBLE_SCHEMAS,
        "producer": PIPELINE_AUTOMATION_PRODUCER,
        "producer_version": _pipeline_automation_producer_version(),
        "local_only": True,
        "run_id": run_id,
        "workflow_source": index_page,
        "profile": profile,
        "status": status,
        "app": str(getattr(env, "app", "") or ""),
        "target": str(getattr(env, "target", "") or ""),
        "lab_dir": str(lab_dir),
        "stages_file": str(stages_file),
        "stages_file_sha256": _safe_file_sha256(stages_file),
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_seconds": duration_seconds,
        "sequence": [idx + 1 for idx in sequence],
        "waves": [[idx + 1 for idx in wave] for wave in waves],
        "max_workers": max_workers,
        "stage_ids": {str(idx + 1): stage_ids.get(idx, "") for idx in sequence},
        "stage_deps": {stage_ids.get(idx, str(idx + 1)): stage_deps.get(idx, []) for idx in sequence},
        "dependency_graph_dot": _pipeline_dependency_dot(
            stage_ids=stage_ids,
            stage_deps=stage_deps,
            waves=waves,
        ),
        "summary": {
            "executed": executed,
            "skipped": skipped,
            "failed": 1 if status == "failed" else 0,
            "stage_count": len(sequence),
        },
        "error": error,
        "stages": stages,
        "run_manifest_path": str(run_path),
        "manifest_path": str(run_path),
        "latest_manifest_path": str(latest_path),
    }
    payload["manifest_sha256"] = _stable_json_sha256({k: v for k, v in payload.items() if k != "manifest_sha256"})
    try:
        _write_json_atomic(run_path, payload)
        if latest_path != run_path:
            _write_json_atomic(latest_path, payload)
        st.session_state[f"{index_page}__last_pipeline_manifest_file"] = str(run_path)
        return run_path
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.debug("Failed to write pipeline automation manifest: %s", exc)
        return None


def _is_missing_mlflow_cli_error(exc: BaseException) -> bool:
    return exc.__class__.__name__ == "MissingMlflowCliError"


def _optional_mlflow_tracking_uri(env: AgiEnv) -> str:
    try:
        return _pipeline_runtime.mlflow_tracking_uri(env)
    except RuntimeError as exc:
        if _is_missing_mlflow_cli_error(exc):
            return ""
        raise


def _normalize_legacy_agi_run_request_code(code: str) -> tuple[str, bool]:
    """Return code compatible with the current RunRequest/StageRequest API."""
    if "StepRequest" not in code and not ("RunRequest" in code and re.search(r"\bsteps\b", code)):
        return code, False
    normalized = code.replace("StepRequest", "StageRequest")
    normalized = re.sub(r"\bsteps\b", "stages", normalized)
    return normalized, normalized != code


def _mlflow_parent_payload(
    env: AgiEnv,
    lab_dir: Path,
    stages_file: Path,
    sequence: List[int],
    *,
    profile: str = "",
    run_id: str = "",
    max_workers: int | None = None,
    waves: List[List[int]] | None = None,
    stage_ids: Mapping[int, str] | None = None,
    stage_deps: Mapping[int, List[str]] | None = None,
) -> tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    run_name = f"{env.app or 'agilab'}:{lab_dir.name}:pipeline"
    tags = {
        "agilab.component": "pipeline",
        "agilab.mlflow.evidence_schema": "workflow.v2",
        "agilab.app": str(getattr(env, "app", "") or ""),
        "agilab.lab": lab_dir.name,
        "agilab.stages_file": str(stages_file),
        "agilab.tracking_uri": _optional_mlflow_tracking_uri(env),
    }
    params = {
        "sequence": ",".join(str(idx + 1) for idx in sequence),
        "stage_count": len(sequence),
        "profile": profile or "balanced",
        "max_workers": max_workers or 1,
        "wave_count": len(waves or []),
        "agilab_version": _pipeline_automation_producer_version(),
    }
    text_artifacts = {
        "pipeline_metadata/sequence.json": json.dumps(
            _pipeline_sequence_metadata(
                env=env,
                lab_dir=lab_dir,
                stages_file=stages_file,
                sequence=sequence,
                profile=profile,
                run_id=run_id,
                max_workers=max_workers,
                waves=waves,
                stage_ids=stage_ids,
                stage_deps=stage_deps,
            ),
            indent=2,
        )
    }
    return run_name, tags, params, text_artifacts


def _pipeline_sequence_metadata(
    *,
    env: AgiEnv,
    lab_dir: Path,
    stages_file: Path,
    sequence: List[int],
    profile: str = "",
    run_id: str = "",
    max_workers: int | None = None,
    waves: List[List[int]] | None = None,
    stage_ids: Mapping[int, str] | None = None,
    stage_deps: Mapping[int, List[str]] | None = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "schema": PIPELINE_SEQUENCE_METADATA_SCHEMA,
        "compatible_schemas": PIPELINE_SEQUENCE_METADATA_COMPATIBLE_SCHEMAS,
        "producer": PIPELINE_AUTOMATION_PRODUCER,
        "producer_version": _pipeline_automation_producer_version(),
        "local_only": True,
        "app": str(getattr(env, "app", "") or ""),
        "target": str(getattr(env, "target", "") or ""),
        "lab_dir": str(lab_dir),
        "stages_file": str(stages_file),
        "sequence": [idx + 1 for idx in sequence],
    }
    if profile:
        payload["profile"] = profile
    if run_id:
        payload["run_id"] = run_id
    if max_workers is not None:
        payload["max_workers"] = max_workers
    if waves is not None:
        payload["waves"] = [[idx + 1 for idx in wave] for wave in waves]
    if stage_ids is not None:
        payload["stage_ids"] = {str(idx + 1): stage_ids.get(idx, "") for idx in sequence}
    if stage_deps is not None and stage_ids is not None:
        payload["stage_deps"] = {stage_ids.get(idx, str(idx + 1)): stage_deps.get(idx, []) for idx in sequence}
    return payload


def _pipeline_automation_metadata(
    *,
    env: AgiEnv,
    workflow_source: str,
    profile: str,
    run_id: str,
    sequence: List[int],
    max_workers: int,
    waves: List[List[int]],
    stage_ids: Mapping[int, str],
    stage_deps: Mapping[int, List[str]],
) -> Dict[str, Any]:
    return {
        "schema": PIPELINE_AUTOMATION_SCHEMA,
        "compatible_schemas": PIPELINE_AUTOMATION_COMPATIBLE_SCHEMAS,
        "producer": PIPELINE_AUTOMATION_PRODUCER,
        "producer_version": _pipeline_automation_producer_version(),
        "local_only": True,
        "workflow_source": workflow_source,
        "app": str(getattr(env, "app", "") or ""),
        "target": str(getattr(env, "target", "") or ""),
        "profile": profile,
        "run_id": run_id,
        "sequence": [idx + 1 for idx in sequence],
        "max_workers": max_workers,
        "waves": [[idx + 1 for idx in wave] for wave in waves],
        "stage_ids": {str(idx + 1): stage_ids.get(idx, "") for idx in sequence},
        "stage_deps": {stage_ids.get(idx, str(idx + 1)): stage_deps.get(idx, []) for idx in sequence},
    }


def _mlflow_stage_payload(
    env: AgiEnv,
    lab_dir: Path,
    stages_file: Path,
    *,
    stage_index: int,
    entry: Dict[str, Any],
    engine: str,
    runtime_root: str,
) -> tuple[str, Dict[str, Any], Dict[str, Any], Dict[str, str]]:
    summary = _pipeline_stages.stage_summary(entry, width=80)
    run_name = f"{env.app or 'agilab'}:{lab_dir.name}:stage_{stage_index + 1}"
    tags = {
        "agilab.component": "pipeline-stage",
        "agilab.mlflow.evidence_schema": "workflow.stage.v2",
        "agilab.app": str(getattr(env, "app", "") or ""),
        "agilab.lab": lab_dir.name,
        "agilab.stages_file": str(stages_file),
        "agilab.stage_index": stage_index + 1,
        "agilab.engine": engine,
        "agilab.runtime": runtime_root or "",
        "agilab.summary": summary,
    }
    params = {
        "description": entry.get("D", ""),
        "question": entry.get("Q", ""),
        "model": entry.get("M", ""),
        "runtime": runtime_root or "",
        "engine": engine,
    }
    text_artifacts = {
        f"stage_{stage_index + 1}/stage_entry.json": json.dumps(
            {
                "stage_index": stage_index + 1,
                "summary": summary,
                "entry": entry,
            },
            indent=2,
        )
    }
    return run_name, tags, params, text_artifacts


def _append_run_log(index_page: str, message: str) -> None:
    """Add a log line to the run log buffer and keep the last 200 entries."""
    key = f"{index_page}__run_logs"
    logs: List[str] = st.session_state.setdefault(key, [])
    logs.append(message)
    if len(logs) > 200:
        st.session_state[key] = logs[-200:]


def _push_run_log(index_page: str, message: str, placeholder: Optional[Any] = None) -> None:
    """Append a log entry and refresh the visible placeholder if provided."""
    _append_run_log(index_page, message)
    log_file_key = f"{index_page}__run_log_file"
    log_file_path = st.session_state.get(log_file_key)
    if log_file_path:
        log_text = (message or "").rstrip("\n")
        if log_text:
            try:
                path_obj = Path(log_file_path).expanduser()
                path_obj.parent.mkdir(parents=True, exist_ok=True)
                with path_obj.open("a", encoding="utf-8") as log_file:
                    log_file.write(log_text + "\n")
            except (OSError, TypeError, ValueError) as exc:
                logger.debug(
                    "Failed to append experiment log to %s: %s",
                    _logging_utils.bound_log_value(log_file_path, _logging_utils.LOG_PATH_LIMIT),
                    _logging_utils.bound_log_value(exc, _logging_utils.LOG_DETAIL_LIMIT),
                )
    if placeholder is not None:
        logs = st.session_state.get(f"{index_page}__run_logs", [])
        if logs:
            placeholder.code("\n".join(logs), height=PIPELINE_RUN_LOG_HEIGHT)
        else:
            placeholder.caption("No runs recorded yet.")


def _rerun_fragment_or_app() -> None:
    """Prefer a fragment rerun when valid; otherwise fall back to a full app rerun."""
    try:
        st.rerun(scope="fragment")
    except StreamlitAPIException:
        st.rerun()


def _prepare_run_log_file(
    index_page: str,
    env: AgiEnv,
    prefix: str,
) -> Tuple[Optional[Path], Optional[str]]:
    """Create and register a log file for the current run context."""
    log_file_key = f"{index_page}__run_log_file"
    app_name = str(getattr(env, "app", "") or "agilab")
    raw_prefix = (prefix or "run").strip()
    safe_prefix = re.sub(r"[^A-Za-z0-9_-]+", "_", raw_prefix).strip("_") or "run"
    log_dir_candidate = getattr(env, "runenv", None) or (Path.home() / "log" / "execute" / app_name)
    try:
        log_dir_path = Path(log_dir_candidate).expanduser()
        log_dir_path.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_file_path = log_dir_path / f"{safe_prefix}_{timestamp}.log"
        log_file_path.write_text("", encoding="utf-8")
        st.session_state[log_file_key] = str(log_file_path)
        st.session_state[f"{index_page}__last_run_log_file"] = str(log_file_path)
        return log_file_path, None
    except (OSError, TypeError, ValueError) as exc:
        st.session_state.pop(log_file_key, None)
        return None, str(exc)


def _get_run_placeholder(index_page: str) -> Optional[Any]:
    """Return the cached run-log placeholder if the UI has rendered it."""
    return st.session_state.get(f"{index_page}__run_placeholder")


def _pipeline_lock_ttl_seconds() -> float:
    """Return lock TTL used to recycle stale pipeline run locks."""
    raw = str(os.environ.get("AGILAB_PIPELINE_LOCK_TTL_SEC", "")).strip()
    if not raw:
        return PIPELINE_LOCK_DEFAULT_TTL_SEC
    try:
        ttl = float(raw)
    except (TypeError, ValueError):
        return PIPELINE_LOCK_DEFAULT_TTL_SEC
    return ttl if ttl > 0 else PIPELINE_LOCK_DEFAULT_TTL_SEC


def _pipeline_lock_path(env: AgiEnv) -> Path:
    """Return shared lock path for one app workflow execution."""
    target = str(getattr(env, "target", "") or getattr(env, "app", "") or "agilab").strip()
    relative = Path(".control") / "pipeline" / target / PIPELINE_LOCK_FILENAME
    try:
        path = env.resolve_share_path(relative)
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError):
        fallback_home = Path(getattr(env, "home_abs", Path.home()) or Path.home())
        path = (fallback_home / ".agilab_pipeline" / target / PIPELINE_LOCK_FILENAME).resolve(strict=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_pipeline_lock_payload(path: Path) -> Dict[str, Any]:
    """Read lock payload and return an empty dict on parse or read failure."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = json.load(stream)
        if isinstance(payload, dict):
            return payload
    except (FileNotFoundError, OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        pass
    return {}


def _pipeline_lock_owner_text(payload: Dict[str, Any], age_sec: Optional[float]) -> str:
    """Format a concise lock owner description for logs and UI."""
    owner_host = str(payload.get("host", "?"))
    owner_pid = payload.get("pid", "?")
    owner_app = str(payload.get("app", "?"))
    age_txt = f"{age_sec:.0f}s" if isinstance(age_sec, (int, float)) else "unknown"
    return f"host={owner_host}, pid={owner_pid}, app={owner_app}, age={age_txt}"


def _pipeline_lock_owner_alive(payload: Dict[str, Any]) -> Optional[bool]:
    """Return whether the lock owner PID appears alive on this host."""
    owner_host = str(payload.get("host", "") or "")
    if not owner_host or owner_host != socket.gethostname():
        return None
    try:
        owner_pid = int(payload.get("pid"))
    except (TypeError, ValueError, OverflowError):
        return None
    if owner_pid <= 0:
        return None
    try:
        os.kill(owner_pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return None


def _inspect_pipeline_run_lock(env: AgiEnv) -> Optional[Dict[str, Any]]:
    """Return current lock metadata for UI and stale-lock decisions."""
    lock_path = _pipeline_lock_path(env)
    if not lock_path.exists():
        return None
    payload = _read_pipeline_lock_payload(lock_path)
    try:
        age_sec: Optional[float] = max(time.time() - lock_path.stat().st_mtime, 0.0)
    except OSError:
        age_sec = None
    owner_alive = _pipeline_lock_owner_alive(payload)
    ttl_sec = _pipeline_lock_ttl_seconds()
    stale_reason: Optional[str] = None
    if isinstance(age_sec, float) and age_sec > ttl_sec:
        stale_reason = f"heartbeat expired ({age_sec:.0f}s > {ttl_sec:.0f}s)"
    elif owner_alive is False:
        stale_reason = "owner process is no longer running on this host"
    return {
        "path": lock_path,
        "payload": payload,
        "age_sec": age_sec,
        "owner_alive": owner_alive,
        "owner_text": _pipeline_lock_owner_text(payload, age_sec),
        "stale_reason": stale_reason,
        "is_stale": bool(stale_reason),
    }


def _clear_pipeline_run_lock(
    env: AgiEnv,
    index_page: str,
    placeholder: Optional[Any] = None,
    *,
    reason: str,
) -> bool:
    """Remove the current workflow lock, if any, and log why."""
    lock_state = _inspect_pipeline_run_lock(env)
    if not lock_state:
        return True
    lock_path = Path(lock_state["path"])
    try:
        lock_path.unlink()
        _push_run_log(
            index_page,
            f"Removed workflow lock ({reason}): {lock_path}",
            placeholder,
        )
        return True
    except FileNotFoundError:
        return True
    except OSError as exc:
        msg = f"Unable to remove workflow lock `{lock_path}`: {exc}"
        st.error(msg)
        _push_run_log(index_page, msg, placeholder)
        return False


def _acquire_pipeline_run_lock(
    env: AgiEnv,
    index_page: str,
    placeholder: Optional[Any] = None,
    *,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Acquire a cross-process workflow lock with stale lock cleanup."""
    lock_path = _pipeline_lock_path(env)
    token = uuid.uuid4().hex
    now = time.time()
    payload = {
        "schema": PIPELINE_LOCK_SCHEMA,
        "token": token,
        "app": str(getattr(env, "app", "")),
        "target": str(getattr(env, "target", "")),
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "created_at": now,
        "heartbeat_at": now,
    }
    log_file_path = str(st.session_state.get(f"{index_page}__run_log_file") or "")
    if log_file_path:
        payload["log_file_path"] = log_file_path

    if force and not _clear_pipeline_run_lock(
        env,
        index_page,
        placeholder,
        reason="forced by user before starting a new run",
    ):
        return None

    for _ in range(2):
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, indent=2)
            _push_run_log(index_page, f"Workflow lock acquired: {lock_path}", placeholder)
            return {"path": lock_path, "token": token}
        except FileExistsError:
            lock_state = _inspect_pipeline_run_lock(env) or {
                "path": lock_path,
                "payload": {},
                "age_sec": None,
                "owner_text": _pipeline_lock_owner_text({}, None),
                "stale_reason": None,
                "is_stale": False,
            }
            if lock_state.get("is_stale"):
                reason = str(lock_state.get("stale_reason") or "stale lock")
                if _clear_pipeline_run_lock(env, index_page, placeholder, reason=reason):
                    continue
                return None

            owner_txt = str(lock_state.get("owner_text") or "?")
            msg = (
                "Another workflow execution is already running. "
                f"Owner: {owner_txt}. Current run cancelled. "
                "If that run was interrupted, use 'Force unlock and run'."
            )
            st.warning(msg)
            _push_run_log(index_page, msg, placeholder)
            return None
        except (OSError, TypeError, ValueError) as exc:
            msg = f"Unable to acquire workflow lock `{lock_path}`: {exc}"
            st.error(msg)
            _push_run_log(index_page, msg, placeholder)
            return None

    msg = f"Unable to acquire workflow lock after stale cleanup retries: {lock_path}"
    st.warning(msg)
    _push_run_log(index_page, msg, placeholder)
    return None


def _refresh_pipeline_run_lock(lock_handle: Optional[Dict[str, Any]]) -> None:
    """Refresh heartbeat for an acquired workflow lock."""
    if not lock_handle:
        return
    lock_path_raw = lock_handle.get("path")
    token = lock_handle.get("token")
    if not lock_path_raw or not token:
        return
    lock_path = Path(lock_path_raw)
    if not lock_path.exists():
        return

    payload = _read_pipeline_lock_payload(lock_path)
    if payload.get("token") != token:
        return
    payload["heartbeat_at"] = time.time()
    tmp_path = lock_path.with_suffix(lock_path.suffix + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        os.replace(tmp_path, lock_path)
    except (OSError, TypeError, ValueError):
        logger.debug("Failed to refresh workflow lock heartbeat for %s", lock_path, exc_info=True)


def _release_pipeline_run_lock(
    lock_handle: Optional[Dict[str, Any]],
    index_page: str,
    placeholder: Optional[Any] = None,
) -> None:
    """Release workflow lock if still owned by this process and token."""
    if not lock_handle:
        return
    lock_path_raw = lock_handle.get("path")
    token = lock_handle.get("token")
    if not lock_path_raw or not token:
        return
    lock_path = Path(lock_path_raw)
    try:
        if not lock_path.exists():
            return
        payload = _read_pipeline_lock_payload(lock_path)
        if payload and payload.get("token") != token:
            return
        lock_path.unlink()
        _push_run_log(index_page, f"Workflow lock released: {lock_path}", placeholder)
    except FileNotFoundError:
        return
    except OSError as exc:
        logger.debug("Failed to release workflow lock %s: %s", lock_path, exc)


def _format_legacy_stage_refs(stale_stages: List[Dict[str, Any]]) -> str:
    refs: List[str] = []
    for item in stale_stages[:5]:
        stage = item.get("stage", "?")
        line = item.get("line", "?")
        summary = str(item.get("summary") or "").strip()
        project = str(item.get("project") or "").strip()
        label = f"stage {stage}, line {line}"
        if project:
            label += f", {project}"
        if summary:
            label += f": {summary}"
        refs.append(label)
    if len(stale_stages) > 5:
        refs.append(f"{len(stale_stages) - 5} more")
    return "; ".join(refs)


def _abort_if_legacy_agi_run_stages(
    index_page: str,
    stages_file: Path,
    stages: List[Dict[str, Any]],
    sequence: List[int],
    placeholder: Optional[Any],
) -> bool:
    """Block stale embedded AGI.run snippets before any pipeline work starts."""
    stale_stages = _pipeline_stages.find_legacy_agi_run_stages(stages, sequence)
    if not stale_stages:
        return False

    detail = _format_legacy_stage_refs(stale_stages)
    message = (
        "Run workflow aborted before execution: the selected stages contain old "
        "AGI.run snippets that call the removed keyword API instead of RunRequest. "
        f"{stale_snippet_cleanup_message([stages_file])} "
        f"Affected stage(s): {detail}."
    )
    st.error(message)
    _push_run_log(index_page, message, placeholder)
    return True


def run_all_stages(
    lab_dir: Path,
    index_page_str: str,
    stages_file: Path,
    module_path: Path,
    env: AgiEnv,
    *,
    load_all_stages_fn: Callable[[Path, Path, str], Optional[List[Dict[str, Any]]]],
    stream_run_command_fn: Callable[..., str],
    log_placeholder: Optional[Any] = None,
    force_lock_clear: bool = False,
    pipeline_profile: str = "balanced",
    pipeline_max_workers: int = 1,
    pipeline_stage_deps: Mapping[str, List[str]] | None = None,
) -> None:
    """Execute selected stages with dependency-aware waves and per-stage virtual environments."""
    if log_placeholder is None:
        log_placeholder = _get_run_placeholder(index_page_str)
    pipeline_profile = _normalize_pipeline_profile(pipeline_profile)
    try:
        pipeline_max_workers = max(1, int(pipeline_max_workers))
    except (TypeError, ValueError):
        pipeline_max_workers = 1
    run_id = uuid.uuid4().hex
    started_at = _utc_timestamp()
    run_started = time.time()
    manifest_stage_records: List[Dict[str, Any]] = []
    skipped = 0
    run_status = "running"
    run_error = ""
    _push_run_log(index_page_str, "Run pipeline invoked.", log_placeholder)
    _push_run_log(
        index_page_str,
        f"Pipeline automation profile: {PIPELINE_AUTOMATION_PROFILE_LABELS.get(pipeline_profile, pipeline_profile)}.",
        log_placeholder,
    )
    stages = load_all_stages_fn(module_path, stages_file, index_page_str) or []
    if not stages:
        st.info(f"No stages available to run from {stages_file}.")
        _push_run_log(index_page_str, "Run workflow aborted: no stages available.", log_placeholder)
        return

    selected_map = st.session_state.setdefault(f"{index_page_str}__venv_map", {})
    engine_map = st.session_state.setdefault(f"{index_page_str}__engine_map", {})
    sequence_state_key = f"{index_page_str}__run_sequence"
    details_store = st.session_state.setdefault(f"{index_page_str}__details", {})
    original_stage = st.session_state[index_page_str][0]
    original_selected = _pipeline_stages.normalize_runtime_path(
        st.session_state.get("lab_selected_venv", "")
    )
    original_engine = st.session_state.get("lab_selected_engine", "")
    snippet_file = st.session_state.get("snippet_file")
    if not snippet_file:
        st.error("Snippet file is not configured. Reload the page and try again.")
        _push_run_log(index_page_str, "Run pipeline aborted: snippet file not configured.", log_placeholder)
        return

    raw_sequence = st.session_state.get(sequence_state_key, [])
    sequence = [idx for idx in raw_sequence if 0 <= idx < len(stages)]
    if not sequence:
        sequence = list(range(len(stages)))

    if _abort_if_legacy_agi_run_stages(index_page_str, stages_file, stages, sequence, log_placeholder):
        return

    waves, dependency_error, stage_ids_by_idx, stage_deps_by_idx = _build_stage_waves(
        stages,
        sequence,
        pipeline_profile,
        dependency_overrides=pipeline_stage_deps,
    )
    if dependency_error:
        st.error(dependency_error)
        _push_run_log(index_page_str, f"Run workflow aborted: {dependency_error}", log_placeholder)
        return
    st.session_state[f"{index_page_str}__last_pipeline_waves"] = [
        [stage_idx + 1 for stage_idx in wave]
        for wave in waves
    ]
    if len(waves) != len(sequence):
        _push_run_log(
            index_page_str,
            f"Workflow dependency planner built {len(waves)} execution wave(s) from {len(sequence)} selected stage(s).",
            log_placeholder,
        )

    lock_handle = _acquire_pipeline_run_lock(
        env,
        index_page_str,
        log_placeholder,
        force=force_lock_clear,
    )
    if lock_handle is None:
        return

    executed = 0
    try:
        parent_run_name, parent_tags, parent_params, parent_text_artifacts = _mlflow_parent_payload(
            env,
            lab_dir,
            stages_file,
            sequence,
            profile=pipeline_profile,
            run_id=run_id,
            max_workers=pipeline_max_workers,
            waves=waves,
            stage_ids=stage_ids_by_idx,
            stage_deps=stage_deps_by_idx,
        )
        parent_tags["agilab.pipeline_profile"] = pipeline_profile
        parent_params["pipeline_profile"] = pipeline_profile
        parent_params["pipeline_max_workers"] = pipeline_max_workers
        parent_text_artifacts["pipeline_metadata/automation.json"] = json.dumps(
            _pipeline_automation_metadata(
                env=env,
                workflow_source=index_page_str,
                profile=pipeline_profile,
                run_id=run_id,
                sequence=sequence,
                max_workers=pipeline_max_workers,
                waves=waves,
                stage_ids=stage_ids_by_idx,
                stage_deps=stage_deps_by_idx,
            ),
            indent=2,
        )
        parent_text_artifacts["pipeline_metadata/dependency_graph.dot"] = _pipeline_dependency_dot(
            stage_ids=stage_ids_by_idx,
            stage_deps=stage_deps_by_idx,
            waves=waves,
        )
        pipeline_log_artifact = st.session_state.get(f"{index_page_str}__run_log_file")
        with _pipeline_runtime.start_tracker_run(
            env,
            run_name=parent_run_name,
            tags=parent_tags,
            params=parent_params,
        ) as pipeline_tracker:
            if pipeline_tracker:
                pipeline_tracker.log_artifacts(
                    text_artifacts=parent_text_artifacts,
                    file_artifacts=[stages_file],
                )
            with st.spinner("Running all stages…"):
                for wave_number, wave in enumerate(waves, start=1):
                    wave_label = ", ".join(str(stage_idx + 1) for stage_idx in wave)
                    _push_run_log(
                        index_page_str,
                        f"Running workflow wave {wave_number}/{len(waves)}: stage(s) {wave_label}.",
                        log_placeholder,
                    )
                    target_base = Path(stages_file).parent.resolve()
                    if target_base.name == target_base.parent.name:
                        target_base = target_base.parent
                    target_base.mkdir(parents=True, exist_ok=True)
                    default_runtime = st.session_state.get("lab_selected_venv", "")
                    if (
                        pipeline_max_workers > 1
                        and _parallel_agi_wave_eligible(
                            stages,
                            wave,
                            profile=pipeline_profile,
                            env=env,
                            stages_file=stages_file,
                            selected_map=selected_map,
                            engine_map=engine_map,
                            default_runtime=default_runtime,
                        )
                    ):
                        _push_run_log(
                            index_page_str,
                            f"Wave {wave_number}: running {len(wave)} AGI stage(s) in parallel with max_workers={pipeline_max_workers}.",
                            log_placeholder,
                        )
                        executed += _run_parallel_agi_wave(
                            stages=stages,
                            wave=wave,
                            profile=pipeline_profile,
                            env=env,
                            index_page=index_page_str,
                            stages_file=stages_file,
                            run_id=run_id,
                            selected_map=selected_map,
                            engine_map=engine_map,
                            default_runtime=default_runtime,
                            target_base=target_base,
                            max_workers=pipeline_max_workers,
                            manifest_stage_records=manifest_stage_records,
                            log_placeholder=log_placeholder,
                        )
                        continue
                    for idx in wave:
                        _refresh_pipeline_run_lock(lock_handle)
                        base_entry = stages[idx]
                        entry, profile_override = _apply_stage_profile(base_entry, pipeline_profile)
                        summary = _pipeline_stages.stage_summary(entry)
                        stage_record: Dict[str, Any] = {
                            "stage_index": idx + 1,
                            "status": "pending",
                        "profile": pipeline_profile,
                        "profile_override_applied": bool(profile_override),
                        "profile_override_keys": sorted(str(key) for key in profile_override),
                        "output_skip_rule": _stage_output_skip_rule(entry),
                        "description": str(entry.get("D", "") or ""),
                        "summary": summary,
                        "engine": "",
                        "runtime": "",
                            "code_sha256": hashlib.sha256(str(entry.get("C", "") or "").encode("utf-8")).hexdigest(),
                            "started_at": "",
                            "finished_at": "",
                            "duration_seconds": None,
                            "outputs": _stage_output_records(entry, env=env, stages_file=stages_file),
                            "error": "",
                        }
                        manifest_stage_records.append(stage_record)
                        if profile_override:
                            _push_run_log(
                                index_page_str,
                                f"Stage {idx + 1}: applied `{pipeline_profile}` profile override.",
                                log_placeholder,
                            )
                        if _stage_disabled(entry):
                            stage_record["status"] = "skipped_disabled"
                            stage_record["finished_at"] = _utc_timestamp()
                            skipped += 1
                            _push_run_log(index_page_str, f"Stage {idx + 1}: skipped by automation profile.", log_placeholder)
                            continue
                        skip_current, output_records = _should_skip_current_outputs(
                            entry,
                            env=env,
                            stages_file=stages_file,
                        )
                        stage_record["outputs"] = output_records
                        if skip_current:
                            stage_record["status"] = "skipped_outputs_exist"
                            stage_record["finished_at"] = _utc_timestamp()
                            skipped += 1
                            _push_run_log(
                                index_page_str,
                                f"Stage {idx + 1}: skipped because declared outputs already exist.",
                                log_placeholder,
                            )
                            continue
                        code = entry.get("C", "")
                        code, normalized_agi_code = _normalize_legacy_agi_run_request_code(str(code or ""))
                        if normalized_agi_code:
                            entry = {**entry, "C": code}
                            _push_run_log(
                                index_page_str,
                                (
                                    f"Stage {idx + 1}: normalized legacy AGI RunRequest snippet "
                                    "from StepRequest/steps to StageRequest/stages."
                                ),
                                log_placeholder,
                            )
                        if not _pipeline_stages.is_runnable_stage(entry):
                            stage_record["status"] = "skipped_not_runnable"
                            stage_record["finished_at"] = _utc_timestamp()
                            skipped += 1
                            continue
                        _push_run_log(index_page_str, f"Running stage {idx + 1}…", log_placeholder)
                        stage_started = time.time()
                        stage_record["status"] = "running"
                        stage_record["started_at"] = _utc_timestamp()

                        raw_runtime = _pipeline_stages.normalize_runtime_path(entry.get("E", ""))
                        venv_path = (
                            raw_runtime if _pipeline_runtime.is_valid_runtime_root(raw_runtime) else ""
                        )
                        if venv_path:
                            selected_map[idx] = venv_path
                            st.session_state["lab_selected_venv"] = venv_path
                        else:
                            selected_map.pop(idx, None)
                        runtime_root = venv_path or st.session_state.get("lab_selected_venv", "")

                        st.session_state[index_page_str][0] = idx
                        st.session_state[index_page_str][1] = entry.get("D", "")
                        st.session_state[index_page_str][2] = entry.get("Q", "")
                        st.session_state[index_page_str][3] = entry.get("M", "")
                        st.session_state[index_page_str][4] = code
                        st.session_state[index_page_str][5] = details_store.get(idx, "")

                        venv_root = runtime_root
                        entry_engine = str(entry.get("R", "") or "")
                        ui_engine = str(engine_map.get(idx) or "")
                        if ui_engine and ui_engine != entry_engine:
                            if entry_engine.startswith("agi.") and ui_engine == "runpy":
                                engine = entry_engine
                            else:
                                engine = ui_engine
                        elif entry_engine:
                            engine = entry_engine
                        else:
                            engine = "agi.run" if venv_root else "runpy"
                        if venv_root and engine == "runpy":
                            engine = "agi.run"
                        if engine.startswith("agi.") and not venv_root:
                            fallback_runtime = _pipeline_stages.normalize_runtime_path(
                                getattr(env, "active_app", "") or ""
                            )
                            if _pipeline_runtime.is_valid_runtime_root(fallback_runtime):
                                venv_root = fallback_runtime
                                st.session_state["lab_selected_venv"] = venv_root
                        stage_record["engine"] = engine
                        stage_record["runtime"] = venv_root or ""

                        stage_run_name, stage_tags, stage_params, stage_text_artifacts = _mlflow_stage_payload(
                            env,
                            lab_dir,
                            stages_file,
                            stage_index=idx,
                            entry=entry,
                            engine=engine,
                            runtime_root=venv_root,
                        )
                        target_base = Path(stages_file).parent.resolve()
                        if target_base.name == target_base.parent.name:
                            target_base = target_base.parent
                        target_base.mkdir(parents=True, exist_ok=True)
                        script_artifact: Optional[Path] = None
                        export_target = st.session_state.get("df_file_out", "")
                        with _pipeline_runtime.start_tracker_run(
                            env,
                            run_name=stage_run_name,
                            tags=stage_tags,
                            params=stage_params,
                            nested=bool(pipeline_tracker),
                        ) as stage_tracker:
                            stage_env = (
                                _pipeline_runtime.build_mlflow_process_env(
                                    env,
                                    run_id=stage_tracker.run_id,
                                )
                                if stage_tracker
                                else {}
                            )
                            stage_env.update(
                                {
                                    "AGILAB_PIPELINE_PROFILE": pipeline_profile,
                                    "AGILAB_PIPELINE_RUN_ID": run_id,
                                    "AGILAB_PIPELINE_STAGE_INDEX": str(idx + 1),
                                    "AGILAB_PIPELINE_MANIFEST": str(_pipeline_manifest_paths(env, index_page_str, run_id)[0]),
                                }
                            )
                            if stage_tracker:
                                stage_tracker.log_artifacts(
                                    text_artifacts=stage_text_artifacts,
                                )
                            if engine == "runpy":
                                output = run_lab(
                                    [entry.get("D", ""), entry.get("Q", ""), code],
                                    snippet_file,
                                    env.copilot_file,
                                    env_overrides=stage_env,
                                )
                                script_artifact = Path(snippet_file)
                            else:
                                script_path = _stage_script_path(target_base, idx)
                                script_path.write_text(_pipeline_runtime.wrap_code_with_mlflow_resume(code))
                                script_artifact = script_path
                                python_cmd = _pipeline_runtime.python_for_stage(
                                    venv_root,
                                    engine=engine,
                                    code=code,
                                )
                                output = stream_run_command_fn(
                                    env,
                                    index_page_str,
                                    [str(python_cmd), str(script_path)],
                                    cwd=target_base,
                                    placeholder=log_placeholder,
                                    extra_env=stage_env,
                                )
                            _refresh_pipeline_run_lock(lock_handle)

                            preview = (output or "").strip()
                            if preview:
                                _push_run_log(
                                    index_page_str,
                                    f"Output (stage {idx + 1}):\n{preview}",
                                    log_placeholder,
                                )
                                if "No such file or directory" in preview:
                                    _push_run_log(
                                        index_page_str,
                                        "Hint: for AGI app stages, input/output data is normally resolved under "
                                        "agi_env.AGI_CLUSTER_SHARE. Check whether the upstream stage created the "
                                        "expected file there before this stage ran.",
                                        log_placeholder,
                                    )
                            else:
                                _push_run_log(
                                    index_page_str,
                                    f"Output (stage {idx + 1}): {engine} executed (no captured stdout)",
                                    log_placeholder,
                                )

                            if isinstance(st.session_state.get("data"), pd.DataFrame) and not st.session_state["data"].empty:
                                if save_csv(st.session_state["data"], export_target):
                                    st.session_state["df_file_in"] = export_target
                                    st.session_state["stage_checked"] = True
                            summary = _pipeline_stages.stage_summary({"Q": entry.get("Q", ""), "C": code})
                            env_label = _pipeline_runtime.label_for_stage_runtime(
                                venv_root,
                                engine=engine,
                                code=code,
                            )
                            _push_run_log(
                                index_page_str,
                                f"Stage {idx + 1}: engine={engine}, env={env_label}, summary=\"{summary}\"",
                                log_placeholder,
                            )
                            if stage_tracker:
                                stage_files = [script_artifact]
                                if export_target:
                                    stage_files.append(export_target)
                                stage_tracker.log_artifacts(
                                    text_artifacts={f"stage_{idx + 1}/stdout.txt": preview or ""},
                                    file_artifacts=stage_files,
                                    tags={
                                        "agilab.status": "completed",
                                        "agilab.output_present": bool(preview),
                                    },
                                )
                            executed += 1
                            stage_record["status"] = "completed"
                            stage_record["finished_at"] = _utc_timestamp()
                            stage_record["duration_seconds"] = max(time.time() - stage_started, 0.0)
                            stage_record["outputs"] = _stage_output_records(
                                entry,
                                env=env,
                                stages_file=stages_file,
                            )
            run_status = "completed"
            if pipeline_tracker:
                pipeline_tracker.log_artifacts(
                    file_artifacts=[pipeline_log_artifact] if pipeline_log_artifact else [],
                    tags={"agilab.status": "completed"},
                    metrics={"executed_stages": executed, "skipped_stages": skipped},
                )

        if executed:
            st.success(f"Executed {executed} stage{'s' if executed != 1 else ''}.")
            _push_run_log(index_page_str, f"Run workflow completed: {executed} stage(s) executed.", log_placeholder)
        else:
            st.info("No runnable code found in the stages.")
            _push_run_log(index_page_str, "Run workflow completed: no runnable code found.", log_placeholder)
    except BaseException as exc:
        run_status = "failed"
        run_error = str(exc)
        for stage_record in reversed(manifest_stage_records):
            if stage_record.get("status") == "running":
                stage_record["status"] = "failed"
                stage_record["finished_at"] = _utc_timestamp()
                stage_record["error"] = run_error
                break
        if "waves" in locals():
            recorded = {
                int(record.get("stage_index", 0)) - 1
                for record in manifest_stage_records
                if int(record.get("stage_index", 0) or 0) > 0
            }
            for wave in waves:
                for pending_idx in wave:
                    if pending_idx in recorded:
                        continue
                    pending_entry, _override = _apply_stage_profile(stages[pending_idx], pipeline_profile)
                    manifest_stage_records.append(
                        {
                            "stage_index": pending_idx + 1,
                            "status": "skipped_after_failure",
                            "profile": pipeline_profile,
                            "profile_override_applied": False,
                            "profile_override_keys": [],
                            "output_skip_rule": _stage_output_skip_rule(pending_entry),
                            "description": str(pending_entry.get("D", "") or ""),
                            "summary": _pipeline_stages.stage_summary(pending_entry),
                            "engine": "",
                            "runtime": "",
                            "code_sha256": hashlib.sha256(str(pending_entry.get("C", "") or "").encode("utf-8")).hexdigest(),
                            "started_at": "",
                            "finished_at": _utc_timestamp(),
                            "duration_seconds": None,
                            "outputs": _stage_output_records(pending_entry, env=env, stages_file=stages_file),
                            "error": "Skipped because an earlier workflow stage failed.",
                        }
                    )
        raise
    finally:
        manifest_path = _write_pipeline_automation_manifest(
            env=env,
            index_page=index_page_str,
            run_id=run_id,
            profile=pipeline_profile,
            status=run_status,
            lab_dir=lab_dir,
            stages_file=stages_file,
            sequence=sequence if "sequence" in locals() else [],
            waves=waves if "waves" in locals() else [],
            max_workers=pipeline_max_workers,
            stage_ids=stage_ids_by_idx if "stage_ids_by_idx" in locals() else {},
            stage_deps=stage_deps_by_idx if "stage_deps_by_idx" in locals() else {},
            stages=manifest_stage_records,
            started_at=started_at,
            finished_at=_utc_timestamp(),
            duration_seconds=max(time.time() - run_started, 0.0)
            if "run_started" in locals()
            else None,
            executed=executed,
            skipped=skipped,
            error=run_error,
        )
        if manifest_path is not None:
            _push_run_log(index_page_str, f"Pipeline automation manifest: {manifest_path}", log_placeholder)
        st.session_state[index_page_str][0] = original_stage
        st.session_state["lab_selected_venv"] = _pipeline_stages.normalize_runtime_path(
            original_selected
        )
        st.session_state["lab_selected_engine"] = original_engine
        st.session_state[f"{index_page_str}__force_blank_q"] = True
        st.session_state[f"{index_page_str}__q_rev"] = st.session_state.get(f"{index_page_str}__q_rev", 0) + 1
        _release_pipeline_run_lock(lock_handle, index_page_str, log_placeholder)
