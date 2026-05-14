# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
import hashlib
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
            package = sys.modules.get("agilab")
            package_path = str(src_root / "agilab")
            package_paths = getattr(package, "__path__", None)
            if package_paths is not None and package_path not in list(package_paths):
                try:
                    package_paths.append(package_path)
                except AttributeError:
                    package.__path__ = [*package_paths, package_path]
            break


_ensure_repo_on_path()

from agi_env import AgiEnv
from agi_env.connector_registry import ConnectorPathRegistry, build_connector_path_registry
from agi_gui.pagelib import render_logo
from agilab.data_connector_facility import (
    DEFAULT_CONNECTORS_RELATIVE_PATH,
    load_connector_catalog,
)
from agilab.data_connector_live_ui import render_connector_live_ui
from agilab.data_connector_resolution import (
    DEFAULT_SETTINGS_RELATIVE_PATH,
    load_app_settings,
)
from agilab.data_connector_ui_preview import build_data_connector_ui_preview
from agilab.ci_artifact_harvest import SCHEMA as CI_ARTIFACT_HARVEST_SCHEMA
from agi_node.reduction import ReduceArtifact

LOWER_IS_BETTER_KEYWORDS = ("mae", "rmse", "mape", "loss", "error", "latency", "duration")
HIGHER_IS_BETTER_KEYWORDS = ("accuracy", "f1", "precision", "recall", "throughput", "score", "auc", "r2")
REDUCE_ARTIFACT_GLOB = "**/reduce_summary_worker_*.json"
MANIFEST_INDEX_FILENAME = "manifest_index.json"
MANIFEST_INDEX_SCHEMA = "agilab.manifest_index.v1"
CI_ARTIFACT_HARVEST_FILENAME = "ci_artifact_harvest.json"
FIRST_PROOF_PATH_ID = "source-checkout-first-proof"
REQUIRED_FIRST_PROOF_VALIDATIONS = ("proof_steps", "target_seconds", "recommended_project")
MANIFEST_SIGNATURE_SUFFIXES = (".sig", ".minisig", ".asc")
APP_DEFAULT_METRICS_GLOBS = {
    "weather_forecast_project": "**/forecast_metrics.json",
}
APP_DEFAULT_REQUIRED_PATTERNS = {
    "weather_forecast_project": ("forecast_metrics.json", "forecast_predictions.csv"),
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


def _connector_path_registry(env: AgiEnv) -> ConnectorPathRegistry:
    return build_connector_path_registry(
        env,
        target=str(env.target),
        first_proof_target="flight",
        run_manifest_filename=RUN_MANIFEST_FILENAME,
    )


def _default_artifact_root(env: AgiEnv) -> Path:
    return _connector_path_registry(env).path("artifact_root")


def _default_metrics_glob(env: AgiEnv) -> str:
    return APP_DEFAULT_METRICS_GLOBS.get(str(env.app), "**/*metrics*.json")


def _default_required_patterns(env: AgiEnv) -> list[str]:
    patterns = APP_DEFAULT_REQUIRED_PATTERNS.get(str(env.app))
    if patterns:
        return list(patterns)
    return ["*.json"]


def _default_run_manifest_path(env: AgiEnv) -> Path:
    return _connector_path_registry(env).path("first_proof_manifest")


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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_metadata(path: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": stat.st_size,
        "modified_at": datetime.fromtimestamp(stat.st_mtime, UTC)
        .isoformat()
        .replace("+00:00", "Z"),
    }


def _manifest_signature_sidecar(path: Path) -> dict[str, Any] | None:
    for suffix in MANIFEST_SIGNATURE_SUFFIXES:
        signature_path = Path(f"{path}{suffix}")
        if not signature_path.is_file():
            continue
        try:
            metadata = _file_metadata(signature_path)
        except OSError:
            continue
        metadata["kind"] = suffix.lstrip(".")
        return metadata
    return None


def _manifest_attachment_metadata(path: Path, provenance: str) -> dict[str, Any]:
    path = path.expanduser()
    try:
        metadata = _file_metadata(path)
    except OSError as exc:
        return {
            "path": str(path),
            "provenance_tag": provenance,
            "verification_status": "unverifiable",
            "signature_status": "missing",
            "error": str(exc),
        }

    signature = _manifest_signature_sidecar(path)
    metadata.update(
        {
            "provenance_tag": provenance,
            "signature_status": "sidecar_present" if signature else "missing",
            "verification_status": "signed" if signature else "provenance_tagged",
            "signature": signature,
        }
    )
    return metadata


def _attachment_field(manifest: dict[str, Any] | None, field: str, default: Any = "") -> Any:
    if not manifest:
        return default
    attachment = manifest.get("attachment")
    if not isinstance(attachment, dict):
        return default
    return attachment.get(field, default)


def _manifest_attachment_status(manifest: dict[str, Any] | None) -> str:
    status = str(_attachment_field(manifest, "verification_status", ""))
    if status:
        return status
    if _attachment_field(manifest, "sha256", ""):
        return "provenance_tagged"
    return "missing"


def _manifest_attachment_sha256(manifest: dict[str, Any] | None) -> str:
    return str(_attachment_field(manifest, "sha256", ""))


def _manifest_attachment_signature_path(manifest: dict[str, Any] | None) -> str:
    signature = _attachment_field(manifest, "signature", None)
    if isinstance(signature, dict):
        return str(signature.get("path", ""))
    return ""


def _manifest_attachment_signature_sha256(manifest: dict[str, Any] | None) -> str:
    signature = _attachment_field(manifest, "signature", None)
    if isinstance(signature, dict):
        return str(signature.get("sha256", ""))
    return ""


def _manifest_attachment_columns(manifest: dict[str, Any] | None, *, prefix: str = "") -> dict[str, Any]:
    attachment = manifest.get("attachment") if isinstance(manifest, dict) else None
    attachment = attachment if isinstance(attachment, dict) else {}
    return {
        f"{prefix}attachment_status": _manifest_attachment_status(manifest),
        f"{prefix}attachment_sha256": attachment.get("sha256", ""),
        f"{prefix}attachment_size_bytes": attachment.get("size_bytes"),
        f"{prefix}attachment_modified_at": attachment.get("modified_at", ""),
        f"{prefix}attachment_provenance_tag": attachment.get("provenance_tag", ""),
        f"{prefix}attachment_signature_path": _manifest_attachment_signature_path(manifest),
        f"{prefix}attachment_signature_sha256": _manifest_attachment_signature_sha256(manifest),
    }


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
        attachment = _manifest_attachment_metadata(path, provenance)
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
            "attachment": attachment,
            **_manifest_attachment_columns({"attachment": attachment}),
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
        "attached_manifest_count": sum(1 for row in rows if row.get("attachment_sha256")),
        "signed_attachment_count": sum(1 for row in rows if row.get("attachment_status") == "signed"),
        "provenance_tagged_attachment_count": sum(
            1 for row in rows if row.get("attachment_status") == "provenance_tagged"
        ),
        "unverifiable_attachment_count": sum(1 for row in rows if row.get("attachment_status") == "unverifiable"),
    }
    return rows, summary


def _parse_ci_artifact_harvest_import_args(raw_value: str) -> tuple[list[Path], list[dict[str, str]]]:
    if not raw_value.strip():
        return [], []
    try:
        tokens = shlex.split(raw_value)
    except ValueError as exc:
        return [], [{"source": "import args", "detail": f"Unable to parse CI artifact harvest args: {exc}"}]

    paths: list[Path] = []
    errors: list[dict[str, str]] = []
    path_flags = {
        "--ci-artifact-harvest",
        "--ci-artifact-harvest-path",
        "--harvest",
    }
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in path_flags:
            if index + 1 >= len(tokens) or tokens[index + 1].startswith("--"):
                errors.append({"source": token, "detail": f"{token} requires a path value"})
                index += 1
                continue
            paths.append(Path(tokens[index + 1]).expanduser())
            index += 2
            continue
        matched_flag = next(
            (
                flag
                for flag in path_flags
                if token.startswith(f"{flag}=")
            ),
            "",
        )
        if matched_flag:
            paths.append(Path(token.split("=", 1)[1]).expanduser())
        elif not token.startswith("--") and Path(token).name == CI_ARTIFACT_HARVEST_FILENAME:
            paths.append(Path(token).expanduser())
        index += 1

    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path.resolve()) if path.exists() else str(path.absolute())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped, errors


def _ci_artifact_harvest_attachment_metadata(path: Path, provenance: str) -> dict[str, Any]:
    path = path.expanduser()
    try:
        metadata = _file_metadata(path)
    except OSError as exc:
        return {
            "path": str(path),
            "provenance_tag": provenance,
            "verification_status": "unverifiable",
            "error": str(exc),
        }
    metadata.update(
        {
            "provenance_tag": provenance,
            "verification_status": "provenance_tagged",
        }
    )
    return metadata


def _ci_artifact_harvest_status(payload: dict[str, Any]) -> str:
    release = payload.get("release", {})
    summary = payload.get("summary", {})
    if (
        payload.get("schema") == CI_ARTIFACT_HARVEST_SCHEMA
        and payload.get("run_status") == "harvest_ready"
        and isinstance(release, dict)
        and release.get("public_status") == "validated"
        and isinstance(summary, dict)
        and int(summary.get("checksum_mismatch_count", 1) or 0) == 0
    ):
        return "validated"
    return "failed"


def _ci_artifact_harvest_summary_counts(
    rows: list[dict[str, Any]],
    *,
    requested_count: int,
    parse_error_count: int,
) -> dict[str, Any]:
    loaded_sources = {
        row.get("source")
        for row in rows
        if row.get("loaded") and row.get("source")
    }
    validated_sources = {
        row.get("source")
        for row in rows
        if row.get("loaded")
        and row.get("source")
        and row.get("harvest_status") == "validated"
    }
    artifact_rows = [row for row in rows if row.get("artifact_kind")]
    release_status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("release_status", "") or "")
        if not status:
            continue
        release_status_counts[status] = release_status_counts.get(status, 0) + 1

    invalid_harvest_count = parse_error_count + sum(
        1 for row in rows if not row.get("loaded")
    )
    failed_harvest_count = len(loaded_sources - validated_sources)
    checksum_mismatch_count = sum(
        1
        for row in artifact_rows
        if row.get("sha256_verified") is not True
    )
    gate_status = "not_configured"
    if requested_count or parse_error_count:
        gate_status = (
            "pass"
            if len(validated_sources) > 0
            and failed_harvest_count == 0
            and invalid_harvest_count == 0
            and checksum_mismatch_count == 0
            else "fail"
        )

    return {
        "args": "",
        "requested_harvest_count": requested_count,
        "loaded_harvest_count": len(loaded_sources),
        "validated_harvest_count": len(validated_sources),
        "failed_harvest_count": failed_harvest_count,
        "invalid_harvest_count": invalid_harvest_count,
        "artifact_count": len(artifact_rows),
        "checksum_verified_count": sum(
            1 for row in artifact_rows if row.get("sha256_verified") is True
        ),
        "checksum_mismatch_count": checksum_mismatch_count,
        "provenance_tagged_count": sum(
            1 for row in artifact_rows if row.get("artifact_attachment_status") == "provenance_tagged"
        ),
        "external_machine_evidence_count": sum(
            1 for row in artifact_rows if row.get("source_machine")
        ),
        "release_status_counts": release_status_counts,
        "gate_status": gate_status,
    }


def _build_ci_artifact_harvest_rows(raw_value: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    harvest_paths, parse_errors = _parse_ci_artifact_harvest_import_args(raw_value)
    rows: list[dict[str, Any]] = [
        {
            "source": error["source"],
            "provenance": "import-args",
            "loaded": False,
            "harvest_schema": "",
            "harvest_run_status": "invalid",
            "harvest_status": "invalid",
            "release_id": "",
            "release_status": "invalid",
            "artifact_id": "",
            "artifact_kind": "",
            "artifact_status": "invalid",
            "artifact_path": "",
            "sha256_verified": False,
            "content_sha256": "",
            "source_machine": "",
            "workflow": "",
            "ci_run_id": "",
            "run_attempt": "",
            "artifact_attachment_status": "missing",
            "detail": error["detail"],
        }
        for error in parse_errors
    ]

    for path in harvest_paths:
        provenance = "--ci-artifact-harvest"
        attachment = _ci_artifact_harvest_attachment_metadata(path, provenance)
        base_row = {
            "source": str(path),
            "provenance": provenance,
            "loaded": False,
            "harvest_schema": "",
            "harvest_run_status": "invalid",
            "harvest_status": "invalid",
            "release_id": "",
            "release_status": "invalid",
            "artifact_id": "",
            "artifact_kind": "",
            "artifact_status": "invalid",
            "artifact_path": "",
            "sha256_verified": False,
            "content_sha256": "",
            "source_machine": "",
            "workflow": "",
            "ci_run_id": "",
            "run_attempt": "",
            "artifact_attachment_status": "missing",
            "detail": "",
            "attachment": attachment,
            "attachment_status": attachment.get("verification_status", ""),
            "attachment_sha256": attachment.get("sha256", ""),
            "attachment_size_bytes": attachment.get("size_bytes"),
            "attachment_modified_at": attachment.get("modified_at", ""),
            "attachment_provenance_tag": attachment.get("provenance_tag", ""),
        }
        try:
            payload = json.loads(path.expanduser().read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("CI artifact harvest must be a JSON object")
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            rows.append({**base_row, "detail": f"Unable to load CI artifact harvest: {exc}"})
            continue

        release = payload.get("release", {})
        summary = payload.get("summary", {})
        artifacts = payload.get("artifacts", [])
        if not isinstance(release, dict):
            release = {}
        if not isinstance(summary, dict):
            summary = {}
        if not isinstance(artifacts, list):
            artifacts = []
        harvest_status = _ci_artifact_harvest_status(payload)
        release_id = str(release.get("release_id", summary.get("release_id", "")) or "")
        release_status = str(release.get("public_status", summary.get("release_status", "")) or "")
        common = {
            **base_row,
            "loaded": True,
            "harvest_schema": str(payload.get("schema", "") or ""),
            "harvest_run_status": str(payload.get("run_status", "") or ""),
            "harvest_status": harvest_status,
            "release_id": release_id,
            "release_status": release_status,
            "detail": "loaded",
        }
        if not artifacts:
            rows.append({**common, "detail": "loaded without artifact rows"})
            continue
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            rows.append(
                {
                    **common,
                    "artifact_id": str(artifact.get("id", "") or ""),
                    "artifact_kind": str(artifact.get("kind", "") or ""),
                    "artifact_status": str(artifact.get("payload_status", "") or ""),
                    "artifact_path": str(artifact.get("path", "") or ""),
                    "sha256_verified": artifact.get("sha256_verified") is True,
                    "content_sha256": str(artifact.get("content_sha256", "") or ""),
                    "source_machine": str(artifact.get("source_machine", "") or ""),
                    "workflow": str(artifact.get("workflow", "") or ""),
                    "ci_run_id": str(artifact.get("run_id", "") or ""),
                    "run_attempt": str(artifact.get("run_attempt", "") or ""),
                    "artifact_attachment_status": str(artifact.get("attachment_status", "") or ""),
                }
            )

    summary = _ci_artifact_harvest_summary_counts(
        rows,
        requested_count=len(harvest_paths),
        parse_error_count=len(parse_errors),
    )
    summary["args"] = raw_value
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
        "attachment": row.get("attachment", {}),
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
        "attached_manifest_count": sum(1 for row in manifest_rows if _manifest_attachment_sha256(row)),
        "signed_attachment_count": sum(1 for row in manifest_rows if _manifest_attachment_status(row) == "signed"),
        "provenance_tagged_attachment_count": sum(
            1 for row in manifest_rows if _manifest_attachment_status(row) == "provenance_tagged"
        ),
        "unverifiable_attachment_count": sum(
            1 for row in manifest_rows if _manifest_attachment_status(row) == "unverifiable"
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
                    **_manifest_attachment_columns(manifest),
                }
            )
    return rows


def _release_display_id(release_key: str, release: dict[str, Any]) -> str:
    return str(release.get("release_id") or Path(str(release_key)).name)


def _manifest_comparison_key(manifest: dict[str, Any]) -> str:
    return str(
        manifest.get("path_id")
        or manifest.get("source")
        or manifest.get("run_id")
        or "unknown"
    )


def _manifest_evidence_rank(manifest: dict[str, Any] | None) -> int:
    if not manifest:
        return -1
    status = str(manifest.get("evidence_status", ""))
    return {
        "invalid": 0,
        "failed": 1,
        "validated": 2,
    }.get(status, 0)


def _manifest_duration(manifest: dict[str, Any] | None) -> float | None:
    if not manifest:
        return None
    value = manifest.get("duration_seconds")
    return float(value) if isinstance(value, (int, float)) else None


def _manifest_duration_sort_value(manifest: dict[str, Any]) -> float:
    duration = _manifest_duration(manifest)
    return -duration if duration is not None else -float("inf")


def _best_manifest_record(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    return sorted(
        records,
        key=lambda record: (
            _manifest_evidence_rank(record["manifest"]),
            _manifest_duration_sort_value(record["manifest"]),
            record["release_id"],
        ),
        reverse=True,
    )[0]


def _manifest_is_same_evidence(current: dict[str, Any], prior: dict[str, Any]) -> bool:
    current_sha256 = _manifest_attachment_sha256(current)
    prior_sha256 = _manifest_attachment_sha256(prior)
    if current_sha256 and current_sha256 == prior_sha256:
        return True
    current_run_id = str(current.get("run_id") or "")
    prior_run_id = str(prior.get("run_id") or "")
    if current_run_id and current_run_id == prior_run_id:
        return True
    current_source = str(current.get("source") or "")
    prior_source = str(prior.get("source") or "")
    return bool(current_source and current_source == prior_source)


def _classify_manifest_comparison(
    current: dict[str, Any] | None,
    prior: dict[str, Any] | None,
) -> tuple[str, str]:
    if current is None:
        return (
            "missing_current_evidence",
            "Prior indexed evidence exists, but the current candidate has no matching manifest.",
        )
    current_status = str(current.get("evidence_status") or "invalid")
    if prior is None:
        if current_status == "validated":
            return "newly_validated", "Current candidate adds validated evidence with no prior indexed match."
        if current_status == "failed":
            return "failed", "Current candidate adds failing evidence with no prior indexed match."
        return "new_evidence_not_validated", "Current candidate adds evidence that is not validated yet."
    prior_status = str(prior.get("evidence_status") or "invalid")
    if current_status == "failed":
        return "failed", "Current candidate evidence is failing."
    if _manifest_is_same_evidence(current, prior):
        return "stale", "Current candidate reuses the same manifest evidence as the prior indexed release."
    current_rank = _manifest_evidence_rank(current)
    prior_rank = _manifest_evidence_rank(prior)
    if current_rank < prior_rank:
        return "regressed", f"Current evidence status {current_status!r} is weaker than prior status {prior_status!r}."
    if current_rank > prior_rank:
        return "improved", f"Current evidence status {current_status!r} improves on prior status {prior_status!r}."
    current_duration = _manifest_duration(current)
    prior_duration = _manifest_duration(prior)
    if current_status == "validated" and prior_status == "validated":
        if current_duration is not None and prior_duration is not None:
            if current_duration < prior_duration:
                return "better", "Current validated evidence is faster than the prior indexed evidence."
            if current_duration > prior_duration:
                return "slower", "Current validated evidence is slower than the prior indexed evidence."
        return "stable", "Current validated evidence matches the prior indexed evidence status."
    return "stable", "Current evidence status matches the prior indexed evidence status."


def _build_manifest_index_comparison_rows(
    existing_index: dict[str, Any],
    current_release: dict[str, Any],
) -> list[dict[str, Any]]:
    current_release_id = str(current_release.get("release_id", "current"))
    current_candidate = str(current_release.get("candidate_bundle_root", ""))
    current_by_key: dict[str, list[dict[str, Any]]] = {}
    for manifest in current_release.get("manifests", []):
        if isinstance(manifest, dict):
            key = _manifest_comparison_key(manifest)
            current_by_key.setdefault(key, []).append(
                {
                    "release_id": current_release_id,
                    "candidate_bundle": current_candidate,
                    "manifest": manifest,
                }
            )

    prior_by_key: dict[str, list[dict[str, Any]]] = {}
    for release_key, release in existing_index.get("releases", {}).items():
        if (
            not isinstance(release, dict)
            or str(release.get("candidate_bundle_root", release_key)) == current_candidate
        ):
            continue
        release_id = _release_display_id(str(release_key), release)
        candidate_bundle = str(release.get("candidate_bundle_root", release_key))
        for manifest in release.get("manifests", []):
            if not isinstance(manifest, dict):
                continue
            key = _manifest_comparison_key(manifest)
            prior_by_key.setdefault(key, []).append(
                {
                    "release_id": release_id,
                    "candidate_bundle": candidate_bundle,
                    "manifest": manifest,
                }
            )

    rows: list[dict[str, Any]] = []
    for key in sorted(set(current_by_key) | set(prior_by_key)):
        current_record = _best_manifest_record(current_by_key.get(key, []))
        prior_record = _best_manifest_record(prior_by_key.get(key, []))
        current_manifest = current_record["manifest"] if current_record else None
        prior_manifest = prior_record["manifest"] if prior_record else None
        comparison_status, detail = _classify_manifest_comparison(current_manifest, prior_manifest)
        rows.append(
            {
                "comparison_key": key,
                "path_id": (
                    (current_manifest or {}).get("path_id")
                    or (prior_manifest or {}).get("path_id")
                    or ""
                ),
                "comparison_status": comparison_status,
                "current_release": current_release_id if current_record else "",
                "current_candidate_bundle": current_candidate if current_record else "",
                "current_run_id": (current_manifest or {}).get("run_id", ""),
                "current_evidence_status": (current_manifest or {}).get("evidence_status", "missing"),
                "current_duration_seconds": _manifest_duration(current_manifest),
                "prior_release": prior_record["release_id"] if prior_record else "",
                "prior_candidate_bundle": prior_record["candidate_bundle"] if prior_record else "",
                "prior_run_id": (prior_manifest or {}).get("run_id", ""),
                "prior_evidence_status": (prior_manifest or {}).get("evidence_status", "missing"),
                "prior_duration_seconds": _manifest_duration(prior_manifest),
                **_manifest_attachment_columns(current_manifest, prefix="current_"),
                **_manifest_attachment_columns(prior_manifest, prefix="prior_"),
                "attachment_match": bool(
                    _manifest_attachment_sha256(current_manifest)
                    and _manifest_attachment_sha256(current_manifest)
                    == _manifest_attachment_sha256(prior_manifest)
                ),
                "detail": detail,
            }
        )
    return rows


def _manifest_index_comparison_summary(
    rows: list[dict[str, Any]],
    existing_index: dict[str, Any],
    current_release: dict[str, Any],
) -> dict[str, Any]:
    current_candidate = str(current_release.get("candidate_bundle_root", ""))
    previous_release_count = sum(
        1
        for release_key, release in existing_index.get("releases", {}).items()
        if isinstance(release, dict)
        and str(release.get("candidate_bundle_root", release_key)) != current_candidate
    )
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("comparison_status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1
    blocking_statuses = {"failed", "missing_current_evidence", "regressed"}
    return {
        "current_release_id": str(current_release.get("release_id", "current")),
        "current_candidate_bundle_root": current_candidate,
        "previous_release_count": previous_release_count,
        "compared_path_count": len(rows),
        "status_counts": dict(sorted(status_counts.items())),
        "better_count": status_counts.get("better", 0),
        "improved_count": status_counts.get("improved", 0),
        "newly_validated_count": status_counts.get("newly_validated", 0),
        "stale_count": status_counts.get("stale", 0),
        "failed_count": status_counts.get("failed", 0),
        "missing_current_count": status_counts.get("missing_current_evidence", 0),
        "blocking_count": sum(status_counts.get(status, 0) for status in blocking_statuses),
    }


def _status_counts(rows: list[dict[str, Any]], key: str = "status") -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get(key, "unknown"))
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _manifest_evidence_from_summary(summary: dict[str, Any], path: Path | str) -> dict[str, Any]:
    loaded = bool(summary.get("loaded"))
    status = str(summary.get("status") or "")
    error = summary.get("error")
    evidence_status = "validated" if loaded and status == "pass" else "failed"
    if error in {"missing", "not_found"}:
        evidence_status = "missing"
    elif not loaded:
        evidence_status = "invalid"
    return {
        "source": str(path),
        "path_id": summary.get("path_id", ""),
        "run_id": summary.get("run_id", ""),
        "manifest_status": status,
        "evidence_status": evidence_status,
        "duration_seconds": summary.get("duration_seconds"),
        "target_seconds": summary.get("target_seconds"),
        "loaded": loaded,
        "detail": error or "selected run manifest summary",
    }


def _selected_release_manifest_evidence(release: dict[str, Any]) -> dict[str, Any] | None:
    manifests = [
        manifest
        for manifest in release.get("manifests", [])
        if isinstance(manifest, dict)
    ]
    first_proof = [
        manifest
        for manifest in manifests
        if manifest.get("path_id") == FIRST_PROOF_PATH_ID
    ]
    best = _best_manifest_record(
        [
            {
                "release_id": str(release.get("release_id", "")),
                "candidate_bundle": str(release.get("candidate_bundle_root", "")),
                "manifest": manifest,
            }
            for manifest in (first_proof or manifests)
        ]
    )
    if best:
        return best["manifest"]
    summary = release.get("selected_run_manifest_summary")
    path = release.get("selected_run_manifest_path")
    if isinstance(summary, dict) and path:
        return _manifest_evidence_from_summary(summary, str(path))
    return None


def _reduce_rows_for_bundle(
    reduce_artifact_rows: list[dict[str, Any]],
    bundle_root: Path,
) -> list[dict[str, Any]]:
    bundle_root = bundle_root.expanduser()
    rows: list[dict[str, Any]] = []
    for row in reduce_artifact_rows:
        path_value = row.get("path")
        if not path_value:
            continue
        try:
            if Path(str(path_value)).expanduser().is_relative_to(bundle_root):
                rows.append(row)
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
    return rows


def _reduce_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    valid_rows = [row for row in rows if row.get("status") == "pass"]
    invalid_rows = [row for row in rows if row.get("status") == "invalid"]
    reducers = sorted({str(row.get("reducer", "")) for row in valid_rows if row.get("reducer")})
    names = sorted({str(row.get("name", "")) for row in valid_rows if row.get("name")})
    return {
        "total_count": len(rows),
        "valid_count": len(valid_rows),
        "invalid_count": len(invalid_rows),
        "reducers": reducers,
        "names": names,
    }


def _compare_reduce_summaries(current: dict[str, Any], target: dict[str, Any]) -> tuple[str, str]:
    if current["invalid_count"]:
        return "invalid_current", "Current bundle has invalid reduce artifacts."
    if target["valid_count"] and not current["valid_count"]:
        return "missing_current", "Target has valid reduce artifacts but the current bundle has none."
    if current["valid_count"] > target["valid_count"]:
        return "expanded", "Current bundle has more valid reduce artifacts than the target."
    if current["valid_count"] < target["valid_count"]:
        return "reduced", "Current bundle has fewer valid reduce artifacts than the target."
    if current["reducers"] != target["reducers"]:
        return "changed", "Current reduce artifact reducers differ from the target."
    if current["valid_count"]:
        return "stable", "Current reduce artifact coverage matches the target."
    return "not_available", "Neither bundle has reduce artifacts."


def _evidence_target_rows(
    *,
    target_kind: str,
    target_release_id: str,
    target_bundle: Path,
    target_metrics_path: Path | None,
    target_metrics_payload: dict[str, Any] | None,
    target_manifest: dict[str, Any] | None,
    candidate_bundle: Path,
    candidate_metrics_payload: dict[str, Any],
    current_manifest: dict[str, Any],
    required_patterns: list[str],
    reduce_artifact_rows: list[dict[str, Any]],
    tolerance_pct: float,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    manifest_status, manifest_detail = _classify_manifest_comparison(current_manifest, target_manifest)
    rows.append(
        {
            "target_kind": target_kind,
            "target_release": target_release_id,
            "target_bundle": str(target_bundle),
            "evidence": "manifest",
            "key": _manifest_comparison_key(current_manifest),
            "status": manifest_status,
            "current_value": current_manifest.get("evidence_status", "missing"),
            "target_value": (target_manifest or {}).get("evidence_status", "missing"),
            "detail": manifest_detail,
        }
    )

    if target_metrics_payload is None:
        rows.append(
            {
                "target_kind": target_kind,
                "target_release": target_release_id,
                "target_bundle": str(target_bundle),
                "evidence": "kpi",
                "key": "metrics_file",
                "status": "missing_target",
                "current_value": "loaded",
                "target_value": str(target_metrics_path or ""),
                "detail": "Target metrics payload could not be loaded.",
            }
        )
    else:
        metric_rows = _build_metric_rows(
            _flatten_numeric_metrics(target_metrics_payload),
            _flatten_numeric_metrics(candidate_metrics_payload),
            tolerance_pct=tolerance_pct,
        )
        for row in metric_rows:
            rows.append(
                {
                    "target_kind": target_kind,
                    "target_release": target_release_id,
                    "target_bundle": str(target_bundle),
                    "evidence": "kpi",
                    "key": row["metric"],
                    "status": row["status"],
                    "current_value": row["candidate"],
                    "target_value": row["baseline"],
                    "detail": row["detail"],
                }
            )

    for row in _build_artifact_rows(target_bundle, candidate_bundle, required_patterns):
        rows.append(
            {
                "target_kind": target_kind,
                "target_release": target_release_id,
                "target_bundle": str(target_bundle),
                "evidence": "artifact",
                "key": row["pattern"],
                "status": row["status"],
                "current_value": row["candidate_count"],
                "target_value": row["baseline_count"],
                "detail": row["detail"],
            }
        )

    current_reduce = _reduce_summary(_reduce_rows_for_bundle(reduce_artifact_rows, candidate_bundle))
    target_reduce = _reduce_summary(_reduce_rows_for_bundle(reduce_artifact_rows, target_bundle))
    reduce_status, reduce_detail = _compare_reduce_summaries(current_reduce, target_reduce)
    rows.append(
        {
            "target_kind": target_kind,
            "target_release": target_release_id,
            "target_bundle": str(target_bundle),
            "evidence": "reduce_artifact",
            "key": "reduce_summary_worker_*.json",
            "status": reduce_status,
            "current_value": current_reduce["valid_count"],
            "target_value": target_reduce["valid_count"],
            "detail": reduce_detail,
        }
    )
    return rows


def _build_evidence_bundle_comparison_rows(
    *,
    existing_index: dict[str, Any],
    baseline_path: Path,
    candidate_path: Path,
    candidate_payload: dict[str, Any],
    run_manifest_path: Path,
    run_manifest_summary: dict[str, Any],
    current_release: dict[str, Any],
    required_patterns: list[str],
    reduce_artifact_rows: list[dict[str, Any]],
    tolerance_pct: float,
) -> list[dict[str, Any]]:
    current_manifest = _selected_release_manifest_evidence(current_release) or _manifest_evidence_from_summary(
        run_manifest_summary,
        run_manifest_path,
    )
    rows = _evidence_target_rows(
        target_kind="baseline",
        target_release_id=baseline_path.parent.name,
        target_bundle=baseline_path.parent,
        target_metrics_path=baseline_path,
        target_metrics_payload=_load_metrics(baseline_path),
        target_manifest=None,
        candidate_bundle=candidate_path.parent,
        candidate_metrics_payload=candidate_payload,
        current_manifest=current_manifest,
        required_patterns=required_patterns,
        reduce_artifact_rows=reduce_artifact_rows,
        tolerance_pct=tolerance_pct,
    )

    current_candidate = str(candidate_path.parent)
    for release_key, release in sorted(existing_index.get("releases", {}).items()):
        if (
            not isinstance(release, dict)
            or str(release.get("candidate_bundle_root", release_key)) == current_candidate
        ):
            continue
        target_bundle = Path(str(release.get("candidate_bundle_root", release_key))).expanduser()
        target_metrics_path = Path(str(release.get("candidate_metrics_file", ""))).expanduser()
        try:
            target_metrics_payload = _load_metrics(target_metrics_path)
        except (OSError, ValueError, json.JSONDecodeError):
            target_metrics_payload = None
        rows.extend(
            _evidence_target_rows(
                target_kind="prior_indexed",
                target_release_id=_release_display_id(str(release_key), release),
                target_bundle=target_bundle,
                target_metrics_path=target_metrics_path,
                target_metrics_payload=target_metrics_payload,
                target_manifest=_selected_release_manifest_evidence(release),
                candidate_bundle=candidate_path.parent,
                candidate_metrics_payload=candidate_payload,
                current_manifest=current_manifest,
                required_patterns=required_patterns,
                reduce_artifact_rows=reduce_artifact_rows,
                tolerance_pct=tolerance_pct,
            )
        )
    return rows


def _evidence_bundle_comparison_summary(rows: list[dict[str, Any]], candidate_path: Path) -> dict[str, Any]:
    blocking_statuses = {
        "fail",
        "failed",
        "invalid_current",
        "missing_current",
        "missing_current_evidence",
        "regressed",
    }
    return {
        "current_candidate_bundle_root": str(candidate_path.parent),
        "target_count": len({(row.get("target_kind"), row.get("target_bundle")) for row in rows}),
        "row_count": len(rows),
        "status_counts": _status_counts(rows),
        "evidence_counts": _status_counts(rows, key="evidence"),
        "blocking_count": sum(
            1 for row in rows if str(row.get("status", "")) in blocking_statuses
        ),
    }


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
    ci_artifact_harvest_summary: dict[str, Any] | None = None,
) -> tuple[str, str]:
    if baseline_path == candidate_path:
        return "needs_review", "Baseline and candidate point to the same metrics file."
    if any(row["status"] == "fail" for row in manifest_rows or []):
        return "blocked", "First-proof run manifest gate is failing or missing."
    if (ci_artifact_harvest_summary or {}).get("gate_status") == "fail":
        return "blocked", "CI artifact harvest gate is failing or incomplete."
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
    ci_artifact_harvest_rows: list[dict[str, Any]],
    ci_artifact_harvest_summary: dict[str, Any],
    manifest_index_path: Path,
    manifest_index_summary: dict[str, Any],
    manifest_index_comparison_rows: list[dict[str, Any]],
    manifest_index_comparison_summary: dict[str, Any],
    evidence_bundle_comparison_rows: list[dict[str, Any]],
    evidence_bundle_comparison_summary: dict[str, Any],
    connector_registry_rows: list[dict[str, Any]],
    connector_registry_summary: dict[str, Any],
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
        "connector_registry_summary": connector_registry_summary,
        "connector_registry_paths": connector_registry_rows,
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
        "ci_artifact_harvest_summary": ci_artifact_harvest_summary,
        "ci_artifact_harvest_evidence": ci_artifact_harvest_rows,
        "manifest_index_path": str(manifest_index_path),
        "manifest_index_summary": manifest_index_summary,
        "manifest_index_comparison": manifest_index_comparison_rows,
        "manifest_index_comparison_summary": manifest_index_comparison_summary,
        "evidence_bundle_comparison": evidence_bundle_comparison_rows,
        "evidence_bundle_comparison_summary": evidence_bundle_comparison_summary,
        "artifact_gates": artifact_rows,
        "metric_gates": metric_rows,
        "reduce_artifacts": reduce_artifact_rows,
    }


def _write_decision(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _release_decision_repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / DEFAULT_CONNECTORS_RELATIVE_PATH).is_file():
            return parent
    return Path.cwd()


def _build_release_decision_connector_preview_state(
    repo_root: Path | None = None,
) -> dict[str, Any]:
    repo_root = (repo_root or _release_decision_repo_root()).resolve()
    settings_path = repo_root / DEFAULT_SETTINGS_RELATIVE_PATH
    catalog_path = repo_root / DEFAULT_CONNECTORS_RELATIVE_PATH
    settings = load_app_settings(settings_path)
    catalog = load_connector_catalog(catalog_path)
    return build_data_connector_ui_preview(
        settings=settings,
        catalog=catalog,
        settings_path=settings_path,
        catalog_path=catalog_path,
    )


def _render_release_decision_connector_live_ui(
    st_api: Any,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    try:
        preview_state = _build_release_decision_connector_preview_state(repo_root)
    except Exception as exc:
        st_api.caption(f"Connector state preview unavailable: {exc}")
        return {
            "schema": "agilab.data_connector_live_ui.v1",
            "component_id": "release_decision_connector_preview",
            "run_status": "unavailable",
            "execution_mode": "streamlit_render_contract_only",
            "summary": {"network_probe_count": 0},
            "issues": [
                {
                    "level": "warning",
                    "location": "release_decision_connector_preview",
                    "message": str(exc),
                }
            ],
        }
    return render_connector_live_ui(
        st_api,
        preview_state,
        component_id="release_decision_connector_preview",
    )


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

connector_registry = _connector_path_registry(env)
connector_registry_rows = connector_registry.as_rows()
connector_registry_summary = connector_registry.summary()
default_root = connector_registry.path("artifact_root")
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
ci_artifact_harvest_args_value = st.sidebar.text_area(
    "CI artifact harvest evidence",
    value=st.session_state.setdefault("release_decision_ci_artifact_harvest_args", ""),
    key="release_decision_ci_artifact_harvest_args",
    height=80,
    help=(
        "Paste `--ci-artifact-harvest /path/ci_artifact_harvest.json` "
        "or a direct `ci_artifact_harvest.json` path."
    ),
)
imported_manifest_rows, imported_manifest_summary = _build_manifest_import_rows(
    manifest_import_args_value
)
ci_artifact_harvest_rows, ci_artifact_harvest_summary = _build_ci_artifact_harvest_rows(
    ci_artifact_harvest_args_value
)
run_manifest_path = _select_run_manifest_gate_path(
    default_run_manifest_path,
    imported_manifest_rows,
)
if run_manifest_path != default_run_manifest_path:
    st.sidebar.caption(f"Using imported first-proof manifest: {run_manifest_path}")

st.session_state["release_decision_connector_live_ui"] = (
    _render_release_decision_connector_live_ui(st)
)

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
manifest_index_comparison_rows = _build_manifest_index_comparison_rows(
    existing_manifest_index,
    current_manifest_index_release,
)
manifest_index_comparison_summary = _manifest_index_comparison_summary(
    manifest_index_comparison_rows,
    existing_manifest_index,
    current_manifest_index_release,
)
evidence_bundle_comparison_rows = _build_evidence_bundle_comparison_rows(
    existing_index=existing_manifest_index,
    baseline_path=baseline_path,
    candidate_path=candidate_path,
    candidate_payload=candidate_payload,
    run_manifest_path=run_manifest_path,
    run_manifest_summary=run_manifest_summary,
    current_release=current_manifest_index_release,
    required_patterns=required_patterns,
    reduce_artifact_rows=reduce_artifact_rows,
    tolerance_pct=tolerance_pct,
)
evidence_bundle_comparison_summary = _evidence_bundle_comparison_summary(
    evidence_bundle_comparison_rows,
    candidate_path,
)
decision_status, decision_summary = _decision_status(
    baseline_path=baseline_path,
    candidate_path=candidate_path,
    artifact_rows=artifact_rows,
    metric_rows=metric_rows,
    manifest_rows=run_manifest_rows,
    ci_artifact_harvest_summary=ci_artifact_harvest_summary,
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
    ci_artifact_harvest_rows=ci_artifact_harvest_rows,
    ci_artifact_harvest_summary=ci_artifact_harvest_summary,
    manifest_index_path=manifest_index_path,
    manifest_index_summary=manifest_index_summary,
    manifest_index_comparison_rows=manifest_index_comparison_rows,
    manifest_index_comparison_summary=manifest_index_comparison_summary,
    evidence_bundle_comparison_rows=evidence_bundle_comparison_rows,
    evidence_bundle_comparison_summary=evidence_bundle_comparison_summary,
    connector_registry_rows=connector_registry_rows,
    connector_registry_summary=connector_registry_summary,
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

st.subheader("Connector path registry")
st.caption("Shared connector roots used for portable artifact, log, and release-evidence paths.")
st.dataframe(pd.DataFrame(connector_registry_rows), width="stretch", hide_index=True)

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

if ci_artifact_harvest_rows or ci_artifact_harvest_summary.get("gate_status") == "fail":
    st.subheader("CI artifact harvest evidence")
    st.caption(
        "External-machine CI evidence imported from `ci_artifact_harvest.json` with checksum and provenance status."
    )
    st.json(ci_artifact_harvest_summary)
    if ci_artifact_harvest_rows:
        st.dataframe(pd.DataFrame(ci_artifact_harvest_rows), width="stretch", hide_index=True)
    else:
        st.info("No CI artifact harvest rows are available.")

manifest_index_rows = _manifest_index_rows(manifest_index_payload)
st.subheader("Per-release manifest index")
st.caption(str(manifest_index_path))
if manifest_index_rows:
    st.dataframe(pd.DataFrame(manifest_index_rows), width="stretch", hide_index=True)
else:
    st.info("No imported run manifests are indexed for this artifact root yet.")

st.subheader("Cross-release manifest comparison")
st.caption(
    "Compares current candidate evidence against prior releases already stored in `manifest_index.json`."
)
if manifest_index_comparison_rows:
    st.dataframe(pd.DataFrame(manifest_index_comparison_rows), width="stretch", hide_index=True)
else:
    st.info("No current or prior indexed run manifests are available for comparison.")

st.subheader("Cross-run evidence bundle comparison")
st.caption(
    "Compares manifest, KPI, required artifact, and reduce-artifact evidence "
    "against the baseline and prior indexed releases."
)
if evidence_bundle_comparison_rows:
    evidence_bundle_comparison_df = pd.DataFrame(evidence_bundle_comparison_rows)
    for column in ("current_value", "target_value"):
        evidence_bundle_comparison_df[column] = evidence_bundle_comparison_df[column].map(
            lambda value: "" if value is None else str(value)
        )
    st.dataframe(evidence_bundle_comparison_df, width="stretch", hide_index=True)
else:
    st.info("No evidence bundle comparison rows are available.")

metric_df = pd.DataFrame(metric_rows)
if metric_df.empty:
    st.info("No shared numeric metrics were available for an automatic KPI gate.")
else:
    st.subheader("KPI gates")
    st.dataframe(metric_df, width="stretch", hide_index=True)

decision_path = candidate_path.parent / "promotion_decision.json"
if st.button("Export promotion decision", type="primary", width="stretch"):
    written = _write_decision(decision_path, payload)
    written_index = _write_manifest_index(manifest_index_path, manifest_index_payload)
    st.success(f"Promotion decision exported to {written}; manifest index exported to {written_index}")

st.download_button(
    "Download decision JSON",
    data=json.dumps(payload, indent=2, sort_keys=True),
    file_name="promotion_decision.json",
    mime="application/json",
    width="stretch",
)
