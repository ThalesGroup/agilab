#!/usr/bin/env python3
"""Emit machine-readable evidence for AGILAB public compatibility claims."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Sequence
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]
MATRIX_RELATIVE_PATH = Path("docs/source/data/compatibility_matrix.toml")
COMPATIBILITY_DOC_RELATIVE_PATH = Path("docs/source/compatibility-matrix.rst")
RUN_MANIFEST_FILENAME = "run_manifest.json"
SUPPORTED_STATUSES = {"validated", "documented"}
REQUIRED_ENTRY_FIELDS = {
    "id",
    "label",
    "status",
    "surface",
    "primary_proof",
    "python",
    "platforms",
    "scope",
    "limits",
}
REQUIRED_PUBLIC_STATUSES = {
    "source-checkout-first-proof": "validated",
    "web-ui-local-first-proof": "validated",
    "agilab-hf-demo": "validated",
    "service-mode-operator-surface": "validated",
    "notebook-quickstart": "documented",
    "published-package-route": "validated",
}
REQUIRED_VALIDATED_EVIDENCE = {
    "source-checkout-first-proof": ("tools/newcomer_first_proof.py", "--json", "run_manifest.json"),
    "web-ui-local-first-proof": ("streamlit run", "src/agilab/main_page.py"),
    "agilab-hf-demo": ("tools/hf_space_smoke.py", "--json"),
    "service-mode-operator-surface": ("tools/service_health_check.py", "health"),
    "published-package-route": (
        'pip install "agilab[examples]"',
        "python -m agilab.lab_run first-proof --json",
    ),
}
DOCUMENTED_BOUNDARY_IDS = {"notebook-quickstart"}


def _load_run_manifest_module(repo_root: Path) -> Any:
    module_path = repo_root / "src" / "agilab" / "run_manifest.py"
    spec = importlib.util.spec_from_file_location(
        "agilab_run_manifest_for_compatibility_report",
        module_path,
    )
    if not spec or not spec.loader:
        raise ModuleNotFoundError(f"Unable to load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _check_result(
    check_id: str,
    label: str,
    passed: bool,
    summary: str,
    *,
    evidence: Sequence[str] = (),
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "evidence": list(evidence),
        "details": details or {},
    }


def _load_matrix(repo_root: Path) -> dict[str, Any]:
    matrix_path = repo_root / MATRIX_RELATIVE_PATH
    with matrix_path.open("rb") as stream:
        payload = tomllib.load(stream)
    entries = payload.get("entries", [])
    if not isinstance(entries, list):
        raise TypeError("compatibility matrix entries must be a list")
    payload["entries"] = [entry for entry in entries if isinstance(entry, dict)]
    return payload


def _entry_statuses(entries: Sequence[dict[str, Any]]) -> dict[str, str]:
    return {str(entry.get("id")): str(entry.get("status")) for entry in entries}


def _dedupe_paths(paths: Sequence[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        expanded = path.expanduser()
        key = str(expanded.resolve()) if expanded.exists() else str(expanded.absolute())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(expanded)
    return deduped


def _default_manifest_search_roots(repo_root: Path) -> list[Path]:
    roots: list[Path] = []
    for env_key in ("AGI_LOG_DIR", "AGILAB_LOG_ABS"):
        env_value = os.environ.get(env_key)
        if env_value:
            roots.append(Path(env_value))
    roots.extend([Path.home() / "log", repo_root / "log"])
    return _dedupe_paths(roots)


def _discover_manifest_paths(
    repo_root: Path,
    *,
    manifest_paths: Sequence[Path] = (),
    manifest_dirs: Sequence[Path] = (),
    include_default_manifests: bool = True,
) -> tuple[list[Path], list[dict[str, str]]]:
    discovered: list[Path] = [Path(path) for path in manifest_paths]
    discovery_errors: list[dict[str, str]] = []

    for directory in manifest_dirs:
        directory = Path(directory).expanduser()
        if directory.is_file():
            discovered.append(directory)
        elif directory.is_dir():
            discovered.extend(sorted(directory.rglob(RUN_MANIFEST_FILENAME)))
        else:
            discovery_errors.append(
                {"path": str(directory), "error": "manifest directory not found"}
            )

    if include_default_manifests:
        for root in _default_manifest_search_roots(repo_root):
            if root.is_file():
                discovered.append(root)
                continue
            if not root.is_dir():
                continue
            default_candidates = [
                root / RUN_MANIFEST_FILENAME,
                *sorted(root.glob(f"*/{RUN_MANIFEST_FILENAME}")),
                *sorted(root.glob(f"execute/*/{RUN_MANIFEST_FILENAME}")),
            ]
            discovered.extend(path for path in default_candidates if path.is_file())

    return _dedupe_paths(discovered), discovery_errors


def _build_manifest_evidence(
    repo_root: Path,
    *,
    manifest_paths: Sequence[Path] = (),
    manifest_dirs: Sequence[Path] = (),
    artifact_index_paths: Sequence[Path] = (),
    include_default_manifests: bool = True,
) -> dict[str, Any]:
    run_manifest = _load_run_manifest_module(repo_root)
    paths, discovery_errors = _discover_manifest_paths(
        repo_root,
        manifest_paths=manifest_paths,
        manifest_dirs=manifest_dirs,
        include_default_manifests=include_default_manifests,
    )
    records: list[dict[str, Any]] = []
    load_failures: list[dict[str, str]] = []

    for path in paths:
        try:
            manifest = run_manifest.load_run_manifest(path)
        except Exception as exc:
            load_failures.append({"path": str(path), "error": str(exc)})
            continue

        summary = run_manifest.manifest_summary(manifest)
        passed = bool(run_manifest.manifest_passed(manifest))
        records.append(
            {
                **summary,
                "source": str(path),
                "evidence_status": "validated" if passed else "failed",
                "passed": passed,
                "source_type": "run_manifest_file",
            }
        )

    artifact_index_records: list[dict[str, Any]] = []
    artifact_index_load_failures: list[dict[str, str]] = []
    artifact_index_release_ids: set[str] = set()
    expanded_artifact_index_paths = [Path(path).expanduser() for path in artifact_index_paths]
    for path in expanded_artifact_index_paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("artifact index must be a JSON object")
            release = payload.get("release", {})
            if not isinstance(release, dict):
                release = {}
            release_id = str(payload.get("release_id") or release.get("release_id", ""))
            if release_id:
                artifact_index_release_ids.add(release_id)
            artifacts = payload.get("artifacts", [])
            if not isinstance(artifacts, list):
                raise ValueError("artifact index must contain an artifacts list")
        except Exception as exc:
            artifact_index_load_failures.append({"path": str(path), "error": str(exc)})
            continue

        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, dict) or artifact.get("kind") != "run_manifest":
                continue
            source = str(artifact.get("path") or f"{path}#artifacts[{index}]")
            artifact_payload = artifact.get("payload")
            try:
                if isinstance(artifact_payload, dict):
                    manifest = run_manifest.RunManifest.from_dict(artifact_payload)
                    summary = run_manifest.manifest_summary(manifest)
                    passed = bool(run_manifest.manifest_passed(manifest))
                else:
                    payload_summary = artifact.get("payload_summary", {})
                    if not isinstance(payload_summary, dict):
                        raise ValueError("run_manifest artifact lacks payload or payload_summary")
                    summary = {
                        "run_id": str(artifact.get("run_id", "")),
                        "path_id": str(payload_summary.get("path_id", "")),
                        "label": str(payload_summary.get("label", "")),
                        "status": str(payload_summary.get("status", "")),
                        "duration_seconds": payload_summary.get("duration_seconds"),
                        "target_seconds": payload_summary.get("target_seconds"),
                        "artifact_count": payload_summary.get("artifact_count", 0),
                        "validation_statuses": payload_summary.get(
                            "validation_statuses",
                            {},
                        ),
                    }
                    passed = artifact.get("payload_status") == "validated"
                if not summary.get("path_id"):
                    raise ValueError("run_manifest artifact does not declare path_id")
            except Exception as exc:
                artifact_index_load_failures.append(
                    {"path": source, "artifact_index": str(path), "error": str(exc)}
                )
                continue

            record = {
                **summary,
                "source": source,
                "evidence_status": "validated" if passed else "failed",
                "passed": passed,
                "source_type": "artifact_index",
                "artifact_index": str(path),
                "release_id": release_id,
                "provider": str(artifact.get("provider") or payload.get("provider", "")),
            }
            artifact_index_records.append(record)
            records.append(record)

    records_by_path_id: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        records_by_path_id.setdefault(str(record.get("path_id")), []).append(record)

    path_statuses = {
        path_id: "validated" if any(record["passed"] for record in path_records) else "failed"
        for path_id, path_records in records_by_path_id.items()
    }
    return {
        "manifest_paths": [str(path) for path in paths],
        "artifact_index_paths": [str(path) for path in expanded_artifact_index_paths],
        "loaded_manifest_count": len(records),
        "loaded_file_manifest_count": len(records) - len(artifact_index_records),
        "loaded_artifact_index_count": len(expanded_artifact_index_paths),
        "artifact_index_manifest_count": len(artifact_index_records),
        "artifact_index_release_ids": sorted(artifact_index_release_ids),
        "artifact_index_records": artifact_index_records,
        "records": records,
        "records_by_path_id": records_by_path_id,
        "path_statuses": path_statuses,
        "load_failures": load_failures,
        "artifact_index_load_failures": artifact_index_load_failures,
        "discovery_errors": discovery_errors,
    }


def _effective_statuses(
    entries: Sequence[dict[str, Any]],
    manifest_evidence: dict[str, Any],
) -> dict[str, str]:
    matrix_statuses = _entry_statuses(entries)
    path_statuses = manifest_evidence.get("path_statuses", {})
    return {
        entry_id: str(path_statuses.get(entry_id, matrix_status))
        for entry_id, matrix_status in matrix_statuses.items()
    }


def _check_matrix_schema(repo_root: Path) -> dict[str, Any]:
    try:
        payload = _load_matrix(repo_root)
        metadata = payload.get("metadata", {})
        entries = payload["entries"]
        failures: list[str] = []
        seen_ids: set[str] = set()
        status_counts = {status: 0 for status in sorted(SUPPORTED_STATUSES)}

        if not isinstance(metadata, dict):
            failures.append("metadata must be a table")
        elif not metadata.get("version") or not metadata.get("updated"):
            failures.append("metadata must include version and updated")

        for index, entry in enumerate(entries):
            entry_id = str(entry.get("id") or f"<entry-{index}>")
            missing_fields = sorted(REQUIRED_ENTRY_FIELDS - set(entry))
            if missing_fields:
                failures.append(f"{entry_id}: missing fields {missing_fields}")
            if entry_id in seen_ids:
                failures.append(f"{entry_id}: duplicate id")
            seen_ids.add(entry_id)

            status = str(entry.get("status"))
            if status not in SUPPORTED_STATUSES:
                failures.append(f"{entry_id}: unsupported status {status!r}")
            else:
                status_counts[status] += 1

            for list_field in ("python", "platforms", "limits"):
                if not isinstance(entry.get(list_field), list) or not entry.get(list_field):
                    failures.append(f"{entry_id}: {list_field} must be a non-empty list")

        details = {
            "entry_count": len(entries),
            "status_counts": status_counts,
            "failures": failures,
            "metadata": metadata,
        }
        ok = not failures and len(entries) > 0
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "compatibility_matrix_schema",
        "Compatibility matrix schema",
        ok,
        (
            "compatibility matrix has typed entries, unique ids, and supported statuses"
            if ok
            else "compatibility matrix schema is incomplete"
        ),
        evidence=[str(MATRIX_RELATIVE_PATH)],
        details=details,
    )


def _check_run_manifest_evidence_ingestion(
    repo_root: Path,
    manifest_evidence: dict[str, Any],
) -> dict[str, Any]:
    try:
        entries = _load_matrix(repo_root)["entries"]
        matrix_ids = {str(entry.get("id")) for entry in entries}
        path_statuses = {
            str(path_id): str(status)
            for path_id, status in manifest_evidence.get("path_statuses", {}).items()
        }
        unknown_path_ids = sorted(set(path_statuses) - matrix_ids)
        failed_path_ids = sorted(
            path_id
            for path_id, status in path_statuses.items()
            if status != "validated"
        )
        load_failures = list(manifest_evidence.get("load_failures", []))
        discovery_errors = list(manifest_evidence.get("discovery_errors", []))
        ok = not unknown_path_ids and not failed_path_ids and not load_failures and not discovery_errors
        loaded_count = int(manifest_evidence.get("loaded_manifest_count", 0))
        details = {
            "loaded_manifest_count": loaded_count,
            "manifest_paths": manifest_evidence.get("manifest_paths", []),
            "path_statuses": path_statuses,
            "records_by_path_id": manifest_evidence.get("records_by_path_id", {}),
            "unknown_path_ids": unknown_path_ids,
            "failed_path_ids": failed_path_ids,
            "load_failures": load_failures,
            "discovery_errors": discovery_errors,
        }
    except Exception as exc:
        ok = False
        loaded_count = 0
        details = {"error": str(exc)}
    return _check_result(
        "run_manifest_evidence_ingestion",
        "Run manifest evidence ingestion",
        ok,
        (
            f"loaded {loaded_count} run manifest(s) and derived compatibility status"
            if loaded_count
            else "run manifest ingestion is wired; no local or external manifests were found"
        )
        if ok
        else "run manifest evidence is invalid, failing, or not mapped to the compatibility matrix",
        evidence=["src/agilab/run_manifest.py", str(MATRIX_RELATIVE_PATH)],
        details=details,
    )


def _check_artifact_index_evidence_ingestion(
    repo_root: Path,
    manifest_evidence: dict[str, Any],
) -> dict[str, Any]:
    try:
        entries = _load_matrix(repo_root)["entries"]
        matrix_ids = {str(entry.get("id")) for entry in entries}
        records = list(manifest_evidence.get("artifact_index_records", []))
        path_statuses = {
            str(record.get("path_id")): "validated"
            if record.get("passed")
            else "failed"
            for record in records
            if record.get("path_id")
        }
        unknown_path_ids = sorted(set(path_statuses) - matrix_ids)
        failed_path_ids = sorted(
            path_id
            for path_id, status in path_statuses.items()
            if status != "validated"
        )
        load_failures = list(manifest_evidence.get("artifact_index_load_failures", []))
        ok = not unknown_path_ids and not failed_path_ids and not load_failures
        loaded_index_count = int(manifest_evidence.get("loaded_artifact_index_count", 0))
        loaded_manifest_count = int(
            manifest_evidence.get("artifact_index_manifest_count", 0)
        )
        details = {
            "loaded_artifact_index_count": loaded_index_count,
            "artifact_index_manifest_count": loaded_manifest_count,
            "artifact_index_paths": manifest_evidence.get("artifact_index_paths", []),
            "artifact_index_release_ids": manifest_evidence.get(
                "artifact_index_release_ids",
                [],
            ),
            "path_statuses": path_statuses,
            "records": records,
            "unknown_path_ids": unknown_path_ids,
            "failed_path_ids": failed_path_ids,
            "load_failures": load_failures,
        }
    except Exception as exc:
        ok = False
        loaded_index_count = 0
        loaded_manifest_count = 0
        details = {"error": str(exc)}
    return _check_result(
        "artifact_index_evidence_ingestion",
        "Artifact-index evidence ingestion",
        ok,
        (
            f"loaded {loaded_manifest_count} run manifest(s) from "
            f"{loaded_index_count} artifact index file(s)"
            if loaded_index_count
            else "artifact-index ingestion is wired; no provider or harvest indexes were supplied"
        )
        if ok
        else "artifact-index evidence is invalid, failing, or not mapped to the compatibility matrix",
        evidence=[
            "tools/github_actions_artifact_index.py",
            "tools/ci_artifact_harvest_report.py",
            str(MATRIX_RELATIVE_PATH),
        ],
        details=details,
    )


def _check_required_public_statuses(
    repo_root: Path,
    manifest_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        entries = _load_matrix(repo_root)["entries"]
        matrix_statuses = _entry_statuses(entries)
        statuses = (
            _effective_statuses(entries, manifest_evidence)
            if manifest_evidence is not None
            else matrix_statuses
        )
        missing = sorted(set(REQUIRED_PUBLIC_STATUSES) - set(statuses))
        mismatched = {
            entry_id: {"expected": expected, "actual": statuses.get(entry_id)}
            for entry_id, expected in REQUIRED_PUBLIC_STATUSES.items()
            if statuses.get(entry_id) != expected
        }
        ok = not missing and not mismatched
        details = {
            "required_statuses": REQUIRED_PUBLIC_STATUSES,
            "matrix_statuses": {
                entry_id: matrix_statuses.get(entry_id)
                for entry_id in sorted(REQUIRED_PUBLIC_STATUSES)
            },
            "actual_statuses": {
                entry_id: statuses.get(entry_id)
                for entry_id in sorted(REQUIRED_PUBLIC_STATUSES)
            },
            "manifest_evidence_statuses": (
                manifest_evidence.get("path_statuses", {})
                if manifest_evidence is not None
                else {}
            ),
            "missing": missing,
            "mismatched": mismatched,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "required_public_statuses",
        "Required public statuses",
        ok,
        (
            "public compatibility paths keep the required validated/documented boundaries"
            if ok
            else "public compatibility paths no longer match the evidence contract"
        ),
        evidence=[str(MATRIX_RELATIVE_PATH)],
        details=details,
    )


def _check_workflow_evidence_commands(repo_root: Path) -> dict[str, Any]:
    try:
        entries = _load_matrix(repo_root)["entries"]
        entry_by_id = {str(entry.get("id")): entry for entry in entries}
        missing: dict[str, list[str]] = {}
        missing_files: dict[str, list[str]] = {}

        for entry_id, required_snippets in REQUIRED_VALIDATED_EVIDENCE.items():
            entry = entry_by_id.get(entry_id, {})
            primary_proof = str(entry.get("primary_proof", ""))
            missing_snippets = [
                snippet for snippet in required_snippets if snippet not in primary_proof
            ]
            if missing_snippets:
                missing[entry_id] = missing_snippets

            missing_paths = [
                snippet
                for snippet in required_snippets
                if snippet.endswith(".py") and not (repo_root / snippet).is_file()
            ]
            if missing_paths:
                missing_files[entry_id] = missing_paths

        ok = not missing and not missing_files
        details = {
            "validated_entries": sorted(REQUIRED_VALIDATED_EVIDENCE),
            "required_evidence": REQUIRED_VALIDATED_EVIDENCE,
            "missing_snippets": missing,
            "missing_files": missing_files,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "workflow_evidence_commands",
        "Workflow evidence commands",
        ok,
        (
            "validated compatibility paths reference executable public proof commands"
            if ok
            else "validated compatibility paths are missing proof command evidence"
        ),
        evidence=[
            str(MATRIX_RELATIVE_PATH),
            "tools/newcomer_first_proof.py",
            "tools/hf_space_smoke.py",
            "tools/service_health_check.py",
        ],
        details=details,
    )


def _check_documented_boundaries(repo_root: Path) -> dict[str, Any]:
    try:
        entries = _load_matrix(repo_root)["entries"]
        statuses = _entry_statuses(entries)
        missing_documented = sorted(
            entry_id
            for entry_id in DOCUMENTED_BOUNDARY_IDS
            if statuses.get(entry_id) != "documented"
        )
        validated_without_evidence = sorted(
            entry_id
            for entry_id, status in statuses.items()
            if status == "validated" and entry_id not in REQUIRED_VALIDATED_EVIDENCE
        )
        ok = not missing_documented and not validated_without_evidence
        details = {
            "documented_boundary_ids": sorted(DOCUMENTED_BOUNDARY_IDS),
            "missing_documented": missing_documented,
            "validated_without_evidence": validated_without_evidence,
        }
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "documented_route_boundaries",
        "Documented route boundaries",
        ok,
        (
            "documented routes remain explicitly outside the validated compatibility slice"
            if ok
            else "documented routes or validation boundaries changed without evidence"
        ),
        evidence=[str(MATRIX_RELATIVE_PATH)],
        details=details,
    )


def _check_docs_report_reference(repo_root: Path) -> dict[str, Any]:
    try:
        doc_text = (repo_root / COMPATIBILITY_DOC_RELATIVE_PATH).read_text(encoding="utf-8")
        normalized_doc = " ".join(doc_text.split())
        required = [
            "tools/compatibility_report.py --compact",
            "tools/compatibility_report.py --artifact-index",
            "workflow-backed compatibility report",
            "required public statuses",
            "run-manifest evidence ingestion",
            "artifact-index evidence ingestion",
        ]
        stale = [
            "broader promotion from this matrix to a "
            "workflow-backed compatibility report"
        ]
        missing = [needle for needle in required if needle not in normalized_doc]
        stale_present = [needle for needle in stale if needle in normalized_doc]
        ok = not missing and not stale_present
        details = {"missing": missing, "stale_present": stale_present}
    except Exception as exc:
        ok = False
        details = {"error": str(exc)}
    return _check_result(
        "compatibility_docs_report_reference",
        "Compatibility docs report reference",
        ok,
        (
            "compatibility docs expose the workflow-backed report command and updated boundary"
            if ok
            else "compatibility docs do not match the workflow-backed report contract"
        ),
        evidence=[str(COMPATIBILITY_DOC_RELATIVE_PATH)],
        details=details,
    )


def build_report(
    *,
    repo_root: Path = REPO_ROOT,
    manifest_paths: Sequence[Path] = (),
    manifest_dirs: Sequence[Path] = (),
    artifact_index_paths: Sequence[Path] = (),
    include_default_manifests: bool = True,
) -> dict[str, Any]:
    repo_root = repo_root.resolve()
    manifest_evidence = _build_manifest_evidence(
        repo_root,
        manifest_paths=manifest_paths,
        manifest_dirs=manifest_dirs,
        artifact_index_paths=artifact_index_paths,
        include_default_manifests=include_default_manifests,
    )
    checks = [
        _check_matrix_schema(repo_root),
        _check_run_manifest_evidence_ingestion(repo_root, manifest_evidence),
        _check_artifact_index_evidence_ingestion(repo_root, manifest_evidence),
        _check_required_public_statuses(repo_root, manifest_evidence),
        _check_workflow_evidence_commands(repo_root),
        _check_documented_boundaries(repo_root),
        _check_docs_report_reference(repo_root),
    ]
    passed = sum(1 for check in checks if check["status"] == "pass")
    failed = sum(1 for check in checks if check["status"] == "fail")
    try:
        entries = _load_matrix(repo_root)["entries"]
        status_counts = {
            status: sum(1 for entry in entries if entry.get("status") == status)
            for status in sorted(SUPPORTED_STATUSES)
        }
        effective_statuses = _effective_statuses(entries, manifest_evidence)
        effective_status_counts = {
            status: sum(1 for actual in effective_statuses.values() if actual == status)
            for status in sorted(set(SUPPORTED_STATUSES) | {"failed"})
        }
    except Exception:
        status_counts = {}
        effective_status_counts = {}
    failed_manifest_paths = [
        path_id
        for path_id, status in manifest_evidence.get("path_statuses", {}).items()
        if status != "validated"
    ]
    return {
        "report": "Compatibility report",
        "status": "pass" if failed == 0 else "fail",
        "summary": {
            "passed": passed,
            "failed": failed,
            "total": len(checks),
            "status_counts": status_counts,
            "effective_status_counts": effective_status_counts,
            "required_public_paths": len(REQUIRED_PUBLIC_STATUSES),
            "workflow_backed_validated_paths": len(REQUIRED_VALIDATED_EVIDENCE),
            "manifest_evidence": {
                "loaded": manifest_evidence.get("loaded_manifest_count", 0),
                "path_ids": sorted(manifest_evidence.get("path_statuses", {})),
                "failed_path_ids": sorted(failed_manifest_paths),
                "load_failures": len(manifest_evidence.get("load_failures", [])),
            },
            "artifact_index_evidence": {
                "loaded_indexes": manifest_evidence.get(
                    "loaded_artifact_index_count",
                    0,
                ),
                "loaded_manifests": manifest_evidence.get(
                    "artifact_index_manifest_count",
                    0,
                ),
                "release_ids": manifest_evidence.get("artifact_index_release_ids", []),
                "load_failures": len(
                    manifest_evidence.get("artifact_index_load_failures", [])
                ),
            },
        },
        "scope": (
            "Validates the public compatibility matrix schema, required public "
            "path statuses, executable proof-command references, and optional "
            "run-manifest and artifact-index evidence. It does not claim broad "
            "OS, network, or remote-topology certification."
        ),
        "checks": checks,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit machine-readable evidence for AGILAB public compatibility claims."
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact JSON without indentation.",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        type=Path,
        help="Load one run_manifest.json as compatibility evidence. May be repeated.",
    )
    parser.add_argument(
        "--manifest-dir",
        action="append",
        default=[],
        type=Path,
        help="Recursively load run_manifest.json files from a directory. May be repeated.",
    )
    parser.add_argument(
        "--artifact-index",
        action="append",
        default=[],
        type=Path,
        help=(
            "Load a provider artifact_index.json or ci_artifact_harvest.json "
            "as compatibility evidence. May be repeated."
        ),
    )
    parser.add_argument(
        "--no-default-manifests",
        action="store_true",
        help="Do not scan default local log roots such as ~/log/execute/*/run_manifest.json.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(list(argv) if argv is not None else None)
    report = build_report(
        manifest_paths=args.manifest,
        manifest_dirs=args.manifest_dir,
        artifact_index_paths=args.artifact_index,
        include_default_manifests=not args.no_default_manifests,
    )
    if args.compact:
        print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    else:
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
