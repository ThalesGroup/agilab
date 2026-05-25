"""Standard evidence exports and verification for AGILAB run manifests."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
from typing import Any, Iterator, Mapping, Sequence
import zipfile

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11 fallback.
    tomllib = None  # type: ignore[assignment]

from agilab import run_manifest


PROOF_PACK_SCHEMA = "agilab.proof_pack.v1"
PROOF_CAPSULE_SCHEMA = "agilab.proof_capsule.v1"
VERIFY_SCHEMA = "agilab.evidence_verification.v1"
CAPSULE_VERIFY_SCHEMA = "agilab.proof_capsule_verification.v1"
POLICY_SCHEMA = "agilab.policy_report.v1"
METADATA_STORE_SCHEMA = "agilab.metadata_store.v1"
CARD_SCHEMA = "agilab.evidence_card.v1"
OPENLINEAGE_EVENT_SCHEMA = "agilab.openlineage_export.v1"
OTEL_EXPORT_SCHEMA = "agilab.otel_trace_export.v1"
DEFAULT_POLICY_ID = "agilab.default_adoption_gate.v1"

PROOF_CAPSULE_EXTENSION = ".agipack"
PROOF_CAPSULE_MANIFEST_FILENAME = "agipack-manifest.json"
PROOF_PACK_FILENAME = "agilab_proof_pack.json"
RUN_MANIFEST_SNAPSHOT_FILENAME = "run_manifest.snapshot.json"
VERIFY_REPORT_FILENAME = "verification-report.json"
POLICY_REPORT_FILENAME = "policy-report.json"
OPENLINEAGE_FILENAME = "openlineage.json"
RO_CRATE_FILENAME = "ro-crate-metadata.json"
OTEL_TRACE_FILENAME = "otel-trace.json"
METADATA_ENTRY_FILENAME = "metadata-store-entry.json"
MODEL_CARD_FILENAME = "model-card.json"
DATASET_CARD_FILENAME = "dataset-card.json"
PROMPT_CARD_FILENAME = "prompt-card.json"
EVAL_CARD_FILENAME = "eval-card.json"

DEFAULT_MANIFEST_CANDIDATES = (
    Path("~/log/execute/flight_telemetry/run_manifest.json"),
    Path("~/log/execute/flight_telemetry/run_manifest.json"),
)

DEFAULT_POLICY_RULES = (
    "manifest_schema_supported",
    "manifest_status_pass",
    "validations_pass",
    "declared_artifacts_present",
    "command_present",
    "replay_available",
)

SECRET_ENV_NAMES = ("SECRET", "TOKEN", "PASSWORD", "PASSWD", "KEY", "CREDENTIAL", "AUTH")


@dataclass(frozen=True)
class ProofPackWriteResult:
    output_dir: Path
    manifest_path: Path
    proof_pack_path: Path
    generated_files: tuple[Path, ...]
    proof_pack: dict[str, Any]


@dataclass(frozen=True)
class ProofCapsuleWriteResult:
    capsule_path: Path
    manifest_path: Path
    capsule_manifest: dict[str, Any]
    proof_pack: dict[str, Any]


def default_manifest_path() -> Path:
    for candidate in DEFAULT_MANIFEST_CANDIDATES:
        expanded = candidate.expanduser()
        if expanded.is_file():
            return expanded
    return DEFAULT_MANIFEST_CANDIDATES[0].expanduser()


def canonical_json_bytes(payload: Mapping[str, Any] | Sequence[Any]) -> bytes:
    return json.dumps(
        _json_safe(payload),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_payload(payload: Mapping[str, Any] | Sequence[Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.expanduser().open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(path: Path) -> run_manifest.RunManifest:
    return run_manifest.load_run_manifest(path.expanduser())


def verify_manifest(manifest_path: Path, *, check_artifacts: bool = True) -> dict[str, Any]:
    manifest_path = manifest_path.expanduser()
    checks: list[dict[str, Any]] = []
    manifest: run_manifest.RunManifest | None = None
    manifest_payload: dict[str, Any] | None = None
    manifest_sha256 = ""

    if not manifest_path.is_file():
        checks.append(_check("manifest_exists", False, f"Missing manifest: {manifest_path}"))
        return _verification_report(manifest_path, manifest_sha256, checks)

    checks.append(_check("manifest_exists", True, "Run manifest exists."))
    try:
        manifest_payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = run_manifest.RunManifest.from_dict(manifest_payload)
        manifest_sha256 = sha256_file(manifest_path)
        checks.append(_check("manifest_schema_supported", True, "Run manifest schema is supported."))
    except Exception as exc:
        checks.append(_check("manifest_schema_supported", False, f"Run manifest is invalid: {exc}"))
        return _verification_report(manifest_path, manifest_sha256, checks)

    checks.append(
        _check(
            "manifest_status_pass",
            manifest.status == "pass",
            f"Run manifest status is {manifest.status!r}.",
            expected="pass",
            actual=manifest.status,
        )
    )
    failed_validations = [
        validation.label
        for validation in manifest.validations
        if validation.status != "pass"
    ]
    checks.append(
        _check(
            "validations_pass",
            not failed_validations and bool(manifest.validations),
            "All manifest validations passed."
            if not failed_validations and manifest.validations
            else "Manifest has failing or missing validations.",
            failed_validations=failed_validations,
            validation_count=len(manifest.validations),
        )
    )
    checks.append(
        _check(
            "command_present",
            bool(manifest.command.argv),
            "Replay command is recorded." if manifest.command.argv else "Replay command is missing.",
            argv_count=len(manifest.command.argv),
        )
    )
    checks.append(
        _check(
            "replay_available",
            _replay_available(manifest),
            "Replay command has a resolvable executable."
            if _replay_available(manifest)
            else "Replay command executable is not resolvable on PATH.",
            executable=manifest.command.argv[0] if manifest.command.argv else "",
        )
    )
    if check_artifacts:
        artifact_checks = [_artifact_check(artifact, manifest_path) for artifact in manifest.artifacts]
        missing = [check for check in artifact_checks if check["status"] == "fail"]
        checks.append(
            _check(
                "declared_artifacts_present",
                not missing,
                "All artifacts declared present still exist."
                if not missing
                else "One or more artifacts declared present are missing.",
                artifact_count=len(artifact_checks),
                missing=[check["path"] for check in missing],
            )
        )
    else:
        checks.append(_check("declared_artifacts_present", True, "Artifact existence checks skipped."))

    checks.append(
        _check(
            "secret_env_values_redacted",
            not _has_unredacted_secret_env(manifest),
            "No secret-like environment values are stored in clear text."
            if not _has_unredacted_secret_env(manifest)
            else "Secret-like environment values are stored in the manifest.",
        )
    )
    report = _verification_report(manifest_path, manifest_sha256, checks)
    report["manifest"] = {
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "label": manifest.label,
        "status": manifest.status,
        "created_at": manifest.created_at,
    }
    report["manifest_payload_sha256"] = sha256_payload(manifest_payload or {})
    return report


def build_openlineage_event(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
) -> dict[str, Any]:
    event_type = "COMPLETE" if manifest.status == "pass" else "FAIL"
    artifacts = [_artifact_dataset_payload(artifact) for artifact in manifest.artifacts]
    return {
        "schema": OPENLINEAGE_EVENT_SCHEMA,
        "eventType": event_type,
        "eventTime": manifest.timing.finished_at or manifest.created_at,
        "producer": "https://github.com/ThalesGroup/agilab",
        "run": {
            "runId": manifest.run_id,
            "facets": {
                "agilab_run_manifest": {
                    "_producer": "https://github.com/ThalesGroup/agilab",
                    "_schemaURL": "https://thalesgroup.github.io/agilab/",
                    "path": str(manifest_path.expanduser()),
                    "sha256": sha256_file(manifest_path) if manifest_path.expanduser().is_file() else "",
                    "path_id": manifest.path_id,
                    "status": manifest.status,
                }
            },
        },
        "job": {
            "namespace": "agilab",
            "name": manifest.path_id or manifest.label or "agilab-run",
        },
        "inputs": [],
        "outputs": artifacts,
    }


def build_ro_crate_metadata(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
) -> dict[str, Any]:
    manifest_id = RUN_MANIFEST_SNAPSHOT_FILENAME
    has_part = [{"@id": manifest_id}]
    artifact_nodes = []
    for artifact in manifest.artifacts:
        artifact_id = _artifact_ro_id(artifact)
        if artifact_id == manifest_id:
            continue
        has_part.append({"@id": artifact_id})
        artifact_nodes.append(
            {
                "@id": artifact_id,
                "@type": "File" if artifact.kind != "directory" else "Dataset",
                "name": artifact.name,
                "encodingFormat": artifact.kind,
                "contentSize": artifact.size_bytes,
                "agilab:declaredExists": artifact.exists,
            }
        )
    return {
        "@context": [
            "https://w3id.org/ro/crate/1.1/context",
            {"agilab": "https://thalesgroup.github.io/agilab/terms#"},
        ],
        "@graph": [
            {
                "@id": "ro-crate-metadata.json",
                "@type": "CreativeWork",
                "conformsTo": {"@id": "https://w3id.org/ro/crate/1.1"},
                "about": {"@id": "./"},
            },
            {
                "@id": "./",
                "@type": "Dataset",
                "name": f"AGILAB proof pack for {manifest.label}",
                "description": "Portable AGILAB evidence bundle with run manifest, policy report, cards, and standard exports.",
                "datePublished": manifest.created_at,
                "hasPart": has_part,
                "agilab:runId": manifest.run_id,
                "agilab:pathId": manifest.path_id,
                "agilab:status": manifest.status,
            },
            {
                "@id": manifest_id,
                "@type": "File",
                "name": run_manifest.RUN_MANIFEST_FILENAME,
                "encodingFormat": "application/json",
                "contentUrl": str(manifest_path.expanduser()),
                "sha256": sha256_file(manifest_path) if manifest_path.expanduser().is_file() else "",
            },
            *artifact_nodes,
        ],
    }


def build_otel_trace_export(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
) -> dict[str, Any]:
    trace_id = hashlib.sha256(manifest.run_id.encode("utf-8")).hexdigest()[:32]
    span_id = hashlib.sha256(f"span:{manifest.run_id}".encode("utf-8")).hexdigest()[:16]
    status_code = "STATUS_CODE_OK" if manifest.status == "pass" else "STATUS_CODE_ERROR"
    return {
        "schema": OTEL_EXPORT_SCHEMA,
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        _otel_attr("service.name", "agilab"),
                        _otel_attr("agilab.run_id", manifest.run_id),
                        _otel_attr("agilab.path_id", manifest.path_id),
                    ]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "agilab.evidence_contract", "version": "1"},
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": manifest.label or manifest.path_id or "agilab.run",
                                "kind": "SPAN_KIND_INTERNAL",
                                "startTimeUnixNano": _iso_to_unix_nanos(manifest.timing.started_at),
                                "endTimeUnixNano": _iso_to_unix_nanos(manifest.timing.finished_at),
                                "attributes": [
                                    _otel_attr("agilab.status", manifest.status),
                                    _otel_attr("agilab.manifest.path", str(manifest_path.expanduser())),
                                    _otel_attr("agilab.manifest.sha256", sha256_file(manifest_path) if manifest_path.expanduser().is_file() else ""),
                                    _otel_attr("agilab.duration_seconds", manifest.timing.duration_seconds),
                                    _otel_attr("agilab.artifact_count", len(manifest.artifacts)),
                                    _otel_attr("agilab.validation_count", len(manifest.validations)),
                                ],
                                "status": {"code": status_code},
                            }
                        ],
                    }
                ],
            }
        ],
    }


def build_metadata_store_entry(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
) -> dict[str, Any]:
    return {
        "schema": "agilab.metadata_entry.v1",
        "entry_type": "run",
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "label": manifest.label,
        "status": manifest.status,
        "created_at": manifest.created_at,
        "manifest_path": str(manifest_path.expanduser()),
        "manifest_sha256": sha256_file(manifest_path) if manifest_path.expanduser().is_file() else "",
        "command": {
            "label": manifest.command.label,
            "argv": list(manifest.command.argv),
            "cwd": manifest.command.cwd,
        },
        "environment": manifest.environment.as_dict(),
        "timing": manifest.timing.as_dict(),
        "artifact_count": len(manifest.artifacts),
        "validation_statuses": {
            validation.label: validation.status
            for validation in manifest.validations
        },
    }


def append_metadata_store(store_path: Path, entry: Mapping[str, Any]) -> dict[str, Any]:
    store_path = store_path.expanduser()
    if store_path.is_file():
        store = json.loads(store_path.read_text(encoding="utf-8"))
        if store.get("schema") != METADATA_STORE_SCHEMA:
            raise ValueError(f"Unsupported metadata store schema: {store.get('schema')!r}")
    else:
        store = {"schema": METADATA_STORE_SCHEMA, "entries": []}

    entries = [dict(item) for item in store.get("entries", []) if isinstance(item, Mapping)]
    run_id = str(entry.get("run_id", ""))
    entries = [item for item in entries if str(item.get("run_id", "")) != run_id]
    entries.append(dict(entry))
    entries.sort(key=lambda item: (str(item.get("created_at", "")), str(item.get("run_id", ""))))
    store = {
        "schema": METADATA_STORE_SCHEMA,
        "entry_count": len(entries),
        "entries": entries,
    }
    _write_json(store_path, store)
    return store


def build_cards(manifest: run_manifest.RunManifest, manifest_path: Path) -> dict[str, dict[str, Any]]:
    artifact_rows = [
        {
            "name": artifact.name,
            "path": artifact.path,
            "kind": artifact.kind,
            "exists": artifact.exists,
            "size_bytes": artifact.size_bytes,
        }
        for artifact in manifest.artifacts
    ]
    base = {
        "schema": CARD_SCHEMA,
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "source_manifest": str(manifest_path.expanduser()),
        "source_manifest_sha256": sha256_file(manifest_path) if manifest_path.expanduser().is_file() else "",
    }
    return {
        "model": {
            **base,
            "card_type": "model",
            "name": _metadata_value(manifest, "model", "not-declared"),
            "intended_use": manifest.label,
            "limitations": [
                "Generated from run evidence only; enrich with domain model metadata before external certification."
            ],
            "metrics": _validation_metrics(manifest),
        },
        "dataset": {
            **base,
            "card_type": "dataset",
            "name": _metadata_value(manifest, "dataset", "not-declared"),
            "artifacts": artifact_rows,
            "known_limitations": [
                "Dataset semantics are inferred from artifact records unless the app declares richer metadata."
            ],
        },
        "prompt": {
            **base,
            "card_type": "prompt",
            "name": _metadata_value(manifest, "prompt", "not-declared"),
            "command_label": manifest.command.label,
            "argv_recorded": bool(manifest.command.argv),
            "argv": list(manifest.command.argv),
            "notes": [
                "Prompt content is not inferred from command arguments; store a redacted prompt artifact when needed."
            ],
        },
        "eval": {
            **base,
            "card_type": "eval",
            "name": f"{manifest.label} evaluation",
            "status": manifest.status,
            "validations": [
                {
                    "label": validation.label,
                    "status": validation.status,
                    "summary": validation.summary,
                }
                for validation in manifest.validations
            ],
        },
    }


def evaluate_policy(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
    *,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    verification = verify_manifest(manifest_path)
    policy = load_policy(policy_path) if policy_path else _default_policy()
    selected_rule_ids = tuple(_policy_rule_ids(policy))
    checks_by_id = {str(check["id"]): check for check in verification["checks"]}
    rules = []
    for rule_id in selected_rule_ids:
        check = checks_by_id.get(rule_id)
        if check is None:
            rules.append(
                {
                    "id": rule_id,
                    "status": "fail",
                    "summary": f"Unknown or unsupported policy rule: {rule_id}",
                }
            )
            continue
        rules.append(
            {
                "id": rule_id,
                "status": check["status"],
                "summary": check["summary"],
                "details": check.get("details", {}),
            }
        )
    status = "pass" if rules and all(rule["status"] == "pass" for rule in rules) else "fail"
    return {
        "schema": POLICY_SCHEMA,
        "policy_id": str(policy.get("id", DEFAULT_POLICY_ID)),
        "status": status,
        "manifest_path": str(manifest_path.expanduser()),
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "rules": rules,
        "verification_status": verification["status"],
    }


def load_policy(policy_path: Path | None) -> dict[str, Any]:
    if policy_path is None:
        return _default_policy()
    policy_path = policy_path.expanduser()
    text = policy_path.read_text(encoding="utf-8")
    if policy_path.suffix.lower() == ".json":
        payload = json.loads(text)
    elif policy_path.suffix.lower() in {".toml", ".tml"}:
        if tomllib is None:
            raise RuntimeError("TOML policy files require Python 3.11 or newer.")
        payload = tomllib.loads(text)
    else:
        raise ValueError("Policy file must be JSON or TOML.")
    if not isinstance(payload, Mapping):
        raise ValueError("Policy file must contain an object.")
    return dict(payload)


def write_proof_pack(
    manifest_path: Path,
    output_dir: Path | None = None,
    *,
    policy_path: Path | None = None,
    metadata_store_path: Path | None = None,
) -> ProofPackWriteResult:
    manifest_path = manifest_path.expanduser()
    manifest = load_manifest(manifest_path)
    output_dir = (output_dir or manifest_path.parent / "agilab-proof-pack").expanduser()
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshot_path = output_dir / RUN_MANIFEST_SNAPSHOT_FILENAME
    shutil.copyfile(manifest_path, snapshot_path)

    exports = {
        VERIFY_REPORT_FILENAME: verify_manifest(manifest_path),
        POLICY_REPORT_FILENAME: evaluate_policy(manifest, manifest_path, policy_path=policy_path),
        OPENLINEAGE_FILENAME: build_openlineage_event(manifest, manifest_path),
        RO_CRATE_FILENAME: build_ro_crate_metadata(manifest, manifest_path),
        OTEL_TRACE_FILENAME: build_otel_trace_export(manifest, manifest_path),
        METADATA_ENTRY_FILENAME: build_metadata_store_entry(manifest, manifest_path),
    }
    cards = build_cards(manifest, manifest_path)
    exports.update(
        {
            MODEL_CARD_FILENAME: cards["model"],
            DATASET_CARD_FILENAME: cards["dataset"],
            PROMPT_CARD_FILENAME: cards["prompt"],
            EVAL_CARD_FILENAME: cards["eval"],
        }
    )

    generated = [snapshot_path]
    for filename, payload in exports.items():
        generated.append(_write_json(output_dir / filename, payload))

    if metadata_store_path is not None:
        append_metadata_store(metadata_store_path, exports[METADATA_ENTRY_FILENAME])

    proof_pack = {
        "schema": PROOF_PACK_SCHEMA,
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "status": exports[VERIFY_REPORT_FILENAME]["status"],
        "source_manifest": {
            "path": str(manifest_path),
            "sha256": sha256_file(manifest_path),
        },
        "output_dir": str(output_dir),
        "files": [
            {
                "name": path.name,
                "path": str(path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted(generated, key=lambda item: item.name)
        ],
        "standards": {
            "openlineage": OPENLINEAGE_FILENAME,
            "ro_crate": RO_CRATE_FILENAME,
            "opentelemetry": OTEL_TRACE_FILENAME,
        },
        "cards": {
            "model": MODEL_CARD_FILENAME,
            "dataset": DATASET_CARD_FILENAME,
            "prompt": PROMPT_CARD_FILENAME,
            "eval": EVAL_CARD_FILENAME,
        },
    }
    proof_pack_path = _write_json(output_dir / PROOF_PACK_FILENAME, proof_pack)
    generated.append(proof_pack_path)
    return ProofPackWriteResult(
        output_dir=output_dir,
        manifest_path=manifest_path,
        proof_pack_path=proof_pack_path,
        generated_files=tuple(generated),
        proof_pack=proof_pack,
    )


def write_proof_capsule(
    manifest_path: Path,
    capsule_path: Path,
    *,
    policy_path: Path | None = None,
    metadata_store_path: Path | None = None,
) -> ProofCapsuleWriteResult:
    """Write a hash-verifiable ``.agipack`` archive for a run manifest.

    The first archive format is intentionally unsigned. It gives reviewers one
    portable ZIP file with per-entry SHA-256 hashes, while keeping detached
    signatures and external provenance attestations as explicit later layers.
    """
    manifest_path = manifest_path.expanduser()
    capsule_path = capsule_path.expanduser()
    capsule_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="agilab-agipack-") as tmp:
        capsule_root = Path(tmp)
        result = write_proof_pack(
            manifest_path,
            capsule_root,
            policy_path=policy_path,
            metadata_store_path=metadata_store_path,
        )

        archive_payload_files = [
            path
            for path in result.generated_files
            if path.name != PROOF_PACK_FILENAME
        ]
        portable_proof_pack = dict(result.proof_pack)
        portable_proof_pack["output_dir"] = "."
        portable_proof_pack["files"] = [
            {
                "name": path.name,
                "path": _archive_relative_path(capsule_root, path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in _sorted_archive_paths(capsule_root, archive_payload_files)
        ]
        _write_json(result.proof_pack_path, portable_proof_pack)
        archive_payload_files.append(result.proof_pack_path)

        entries = [
            {
                "path": _archive_relative_path(capsule_root, path),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in _sorted_archive_paths(capsule_root, archive_payload_files)
        ]
        capsule_manifest = {
            "schema": PROOF_CAPSULE_SCHEMA,
            "created_at": run_manifest.utc_now(),
            "format": "zip",
            "signed": False,
            "signature": None,
            "integrity": "sha256-per-entry",
            "run_id": result.proof_pack["run_id"],
            "path_id": result.proof_pack["path_id"],
            "status": result.proof_pack["status"],
            "root": PROOF_PACK_FILENAME,
            "source_manifest": result.proof_pack["source_manifest"],
            "standards": result.proof_pack["standards"],
            "cards": result.proof_pack["cards"],
            "entry_count": len(entries),
            "entries": entries,
            "limitations": [
                "This .agipack is hash-verifiable but not cryptographically signed.",
                (
                    "External Sigstore, SLSA, or PyPI attestations must be carried "
                    "as separate evidence files until a signed capsule layer ships."
                ),
            ],
        }
        capsule_manifest_path = _write_json(
            capsule_root / PROOF_CAPSULE_MANIFEST_FILENAME,
            capsule_manifest,
        )

        with zipfile.ZipFile(
            capsule_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for path in _sorted_archive_paths(
                capsule_root,
                [*archive_payload_files, capsule_manifest_path],
            ):
                archive.write(path, _archive_relative_path(capsule_root, path))

    return ProofCapsuleWriteResult(
        capsule_path=capsule_path,
        manifest_path=manifest_path,
        capsule_manifest=capsule_manifest,
        proof_pack=portable_proof_pack,
    )


def verify_proof_capsule(capsule_path: Path) -> dict[str, Any]:
    capsule_path = capsule_path.expanduser()
    checks: list[dict[str, Any]] = []
    manifest: run_manifest.RunManifest | None = None

    if not capsule_path.is_file():
        checks.append(
            _check("capsule_exists", False, f"Missing proof capsule: {capsule_path}")
        )
        return _capsule_verification_report(capsule_path, "", checks)

    checks.append(_check("capsule_exists", True, "Proof capsule exists."))
    capsule_sha256 = sha256_file(capsule_path)
    try:
        with zipfile.ZipFile(capsule_path) as archive:
            archive_entries = sorted(
                name
                for name in archive.namelist()
                if name and not name.endswith("/")
            )
            checks.append(
                _check("zip_readable", True, "Proof capsule ZIP can be read.")
            )

            unsafe_entries = [
                name
                for name in archive_entries
                if not _safe_archive_member_name(name)
            ]
            checks.append(
                _check(
                    "archive_paths_safe",
                    not unsafe_entries,
                    "Archive member paths are relative and safe."
                    if not unsafe_entries
                    else "Archive contains unsafe member paths.",
                    unsafe_entries=unsafe_entries,
                )
            )

            if PROOF_CAPSULE_MANIFEST_FILENAME not in archive_entries:
                checks.append(
                    _check(
                        "capsule_manifest_present",
                        False,
                        f"Missing {PROOF_CAPSULE_MANIFEST_FILENAME}.",
                    )
                )
                return _capsule_verification_report(capsule_path, capsule_sha256, checks)

            checks.append(
                _check(
                    "capsule_manifest_present",
                    True,
                    "Capsule manifest exists.",
                )
            )
            try:
                capsule_manifest = json.loads(
                    archive.read(PROOF_CAPSULE_MANIFEST_FILENAME).decode("utf-8")
                )
            except Exception as exc:
                checks.append(
                    _check(
                        "capsule_manifest_schema_supported",
                        False,
                        f"Capsule manifest is invalid JSON: {exc}",
                    )
                )
                return _capsule_verification_report(capsule_path, capsule_sha256, checks)

            schema_ok = (
                isinstance(capsule_manifest, Mapping)
                and capsule_manifest.get("schema") == PROOF_CAPSULE_SCHEMA
            )
            actual_schema = (
                capsule_manifest.get("schema")
                if isinstance(capsule_manifest, Mapping)
                else type(capsule_manifest).__name__
            )
            checks.append(
                _check(
                    "capsule_manifest_schema_supported",
                    schema_ok,
                    "Capsule manifest schema is supported."
                    if schema_ok
                    else f"Unsupported capsule manifest schema: {actual_schema}",
                )
            )
            if not schema_ok:
                return _capsule_verification_report(capsule_path, capsule_sha256, checks)

            entries = capsule_manifest.get("entries", [])
            if not isinstance(entries, list):
                checks.append(
                    _check(
                        "capsule_entries_valid",
                        False,
                        "Capsule entries must be a list.",
                    )
                )
                return _capsule_verification_report(capsule_path, capsule_sha256, checks)

            entry_rows = [dict(entry) for entry in entries if isinstance(entry, Mapping)]
            expected_paths = [str(entry.get("path", "")) for entry in entry_rows]
            duplicate_paths = sorted(
                {path for path in expected_paths if expected_paths.count(path) > 1}
            )
            invalid_paths = [
                path
                for path in expected_paths
                if not _safe_archive_member_name(path)
            ]
            checks.append(
                _check(
                    "capsule_entries_valid",
                    len(entry_rows) == len(entries)
                    and not duplicate_paths
                    and not invalid_paths,
                    "Capsule entries are valid and unique."
                    if (
                        len(entry_rows) == len(entries)
                        and not duplicate_paths
                        and not invalid_paths
                    )
                    else "Capsule entries are malformed, duplicated, or unsafe.",
                    duplicate_paths=duplicate_paths,
                    invalid_paths=invalid_paths,
                    declared_entry_count=len(entries),
                )
            )

            expected_set = set(expected_paths)
            archive_payload_set = set(archive_entries) - {PROOF_CAPSULE_MANIFEST_FILENAME}
            missing_entries = sorted(expected_set - archive_payload_set)
            unexpected_entries = sorted(archive_payload_set - expected_set)
            checks.append(
                _check(
                    "capsule_entry_inventory_matches",
                    not missing_entries and not unexpected_entries,
                    "Archive inventory matches the capsule manifest."
                    if not missing_entries and not unexpected_entries
                    else "Archive inventory differs from the capsule manifest.",
                    missing_entries=missing_entries,
                    unexpected_entries=unexpected_entries,
                )
            )

            hash_failures = []
            for entry in entry_rows:
                name = str(entry.get("path", ""))
                if name not in archive_payload_set:
                    continue
                data = archive.read(name)
                expected_sha256 = str(entry.get("sha256", ""))
                try:
                    expected_size = int(entry.get("size_bytes", -1))
                except (TypeError, ValueError):
                    expected_size = -1
                actual_sha256 = hashlib.sha256(data).hexdigest()
                actual_size = len(data)
                if actual_sha256 != expected_sha256 or actual_size != expected_size:
                    hash_failures.append(
                        {
                            "path": name,
                            "expected_sha256": expected_sha256,
                            "actual_sha256": actual_sha256,
                            "expected_size_bytes": expected_size,
                            "actual_size_bytes": actual_size,
                        }
                    )
            checks.append(
                _check(
                    "capsule_entry_hashes_match",
                    not hash_failures,
                    "All capsule entry hashes and sizes match."
                    if not hash_failures
                    else "One or more capsule entries failed hash or size verification.",
                    failures=hash_failures,
                )
            )

            try:
                manifest_payload = _read_archive_json(
                    archive,
                    RUN_MANIFEST_SNAPSHOT_FILENAME,
                )
                manifest = run_manifest.RunManifest.from_dict(manifest_payload)
                checks.append(
                    _check(
                        "run_manifest_snapshot_valid",
                        True,
                        "Run manifest snapshot is valid.",
                    )
                )
            except Exception as exc:
                checks.append(
                    _check(
                        "run_manifest_snapshot_valid",
                        False,
                        f"Run manifest snapshot is invalid: {exc}",
                    )
                )

            try:
                proof_pack_payload = _read_archive_json(archive, PROOF_PACK_FILENAME)
            except Exception as exc:
                proof_pack_payload = {}
                proof_pack_error = str(exc)
            else:
                proof_pack_error = ""
            proof_pack_schema_ok = proof_pack_payload.get("schema") == PROOF_PACK_SCHEMA
            snapshot_sha256 = (
                hashlib.sha256(archive.read(RUN_MANIFEST_SNAPSHOT_FILENAME)).hexdigest()
                if RUN_MANIFEST_SNAPSHOT_FILENAME in archive_payload_set
                else ""
            )
            source_sha256 = str(
                dict(proof_pack_payload.get("source_manifest", {})).get("sha256", "")
            )
            proof_pack_ok = (
                proof_pack_schema_ok
                and bool(snapshot_sha256)
                and source_sha256 == snapshot_sha256
            )
            checks.append(
                _check(
                    "proof_pack_manifest_valid",
                    proof_pack_ok,
                    "Proof-pack manifest is valid and matches the run manifest snapshot."
                    if proof_pack_ok
                    else "Proof-pack manifest is missing, unsupported, or points at a different run manifest hash.",
                    proof_pack_schema=proof_pack_payload.get("schema"),
                    proof_pack_error=proof_pack_error,
                    source_manifest_sha256=source_sha256,
                    snapshot_sha256=snapshot_sha256,
                )
            )
    except zipfile.BadZipFile as exc:
        checks.append(
            _check(
                "zip_readable",
                False,
                f"Proof capsule is not a readable ZIP: {exc}",
            )
        )
        return _capsule_verification_report(capsule_path, capsule_sha256, checks)
    except KeyError as exc:
        checks.append(
            _check(
                "capsule_required_files_present",
                False,
                f"Missing required archive member: {exc}",
            )
        )
        return _capsule_verification_report(capsule_path, capsule_sha256, checks)

    report = _capsule_verification_report(capsule_path, capsule_sha256, checks)
    if manifest is not None:
        report["manifest"] = {
            "run_id": manifest.run_id,
            "path_id": manifest.path_id,
            "label": manifest.label,
            "status": manifest.status,
            "created_at": manifest.created_at,
        }
    return report


@contextmanager
def _manifest_input(input_path: Path) -> Iterator[tuple[run_manifest.RunManifest, Path]]:
    input_path = input_path.expanduser()
    if _is_proof_capsule(input_path):
        with tempfile.TemporaryDirectory(prefix="agilab-agipack-manifest-") as tmp:
            target = Path(tmp) / RUN_MANIFEST_SNAPSHOT_FILENAME
            with zipfile.ZipFile(input_path) as archive:
                target.write_bytes(archive.read(RUN_MANIFEST_SNAPSHOT_FILENAME))
            yield load_manifest(target), target
    else:
        yield load_manifest(input_path), input_path


def replay_payload(manifest: run_manifest.RunManifest) -> dict[str, Any]:
    return {
        "schema": "agilab.replay_plan.v1",
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "command": {
            "label": manifest.command.label,
            "argv": list(manifest.command.argv),
            "cwd": manifest.command.cwd,
            "env_overrides": dict(manifest.command.env_overrides),
        },
        "safe_default": "print-only",
        "execute_requires": "--execute",
    }


def run_replay(
    manifest: run_manifest.RunManifest,
    *,
    execute: bool = False,
    timeout_seconds: float | None = None,
) -> tuple[int, dict[str, Any]]:
    payload = replay_payload(manifest)
    argv = list(manifest.command.argv)
    if not execute:
        return 0, payload
    if not argv:
        payload["status"] = "fail"
        payload["error"] = "No replay command recorded."
        return 2, payload
    env = os.environ.copy()
    env.update(manifest.command.env_overrides)
    completed = subprocess.run(
        argv,
        cwd=manifest.command.cwd or None,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_seconds,
        check=False,
    )
    payload["status"] = "pass" if completed.returncode == 0 else "fail"
    payload["returncode"] = completed.returncode
    payload["stdout"] = completed.stdout
    payload["stderr"] = completed.stderr
    return completed.returncode, payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    input_path = Path(args.manifest).expanduser() if args.manifest else default_manifest_path()

    if args.command == "verify":
        report = (
            verify_proof_capsule(input_path)
            if _is_proof_capsule(input_path)
            else verify_manifest(input_path, check_artifacts=not args.no_artifacts)
        )
        return _emit_report(report, json_output=args.json, strict=args.strict)

    if args.command == "prove":
        if _is_proof_capsule(input_path):
            raise SystemExit("agilab prove expects a run_manifest.json input, not an existing .agipack.")
        if args.export:
            result = write_proof_capsule(
                input_path,
                Path(args.export).expanduser(),
                policy_path=Path(args.policy).expanduser() if args.policy else None,
                metadata_store_path=Path(args.metadata_store).expanduser() if args.metadata_store else None,
            )
            payload = result.capsule_manifest | {"capsule_path": str(result.capsule_path)}
            return _emit_report(payload, json_output=args.json, strict=False)
        result = write_proof_pack(
            input_path,
            Path(args.output_dir).expanduser() if args.output_dir else None,
            policy_path=Path(args.policy).expanduser() if args.policy else None,
            metadata_store_path=Path(args.metadata_store).expanduser() if args.metadata_store else None,
        )
        payload = result.proof_pack | {"proof_pack_path": str(result.proof_pack_path)}
        return _emit_report(payload, json_output=args.json, strict=False)

    with _manifest_input(input_path) as (manifest, manifest_path):
        if args.command == "replay":
            rc, payload = run_replay(
                manifest,
                execute=args.execute,
                timeout_seconds=args.timeout,
            )
            if _is_proof_capsule(input_path):
                payload["source_capsule"] = str(input_path)
            return _emit_report(payload, json_output=args.json, strict=args.execute and rc != 0)

        if args.command in {"export-lineage", "export-traces"}:
            export_format = "otel" if args.command == "export-traces" else args.format
            payloads = _selected_exports(manifest, manifest_path, export_format)
            paths = _write_selected_exports(payloads, args.output, args.output_dir)
            report = {
                "schema": "agilab.evidence_exports.v1",
                "manifest_path": str(manifest_path),
                "source_capsule": str(input_path) if _is_proof_capsule(input_path) else None,
                "formats": sorted(payloads),
                "paths": {key: str(value) for key, value in sorted(paths.items())},
            }
            return _emit_report(report, json_output=args.json, strict=False)

        if args.command == "policy-check":
            report = evaluate_policy(
                manifest,
                manifest_path,
                policy_path=Path(args.policy).expanduser() if args.policy else None,
            )
            if _is_proof_capsule(input_path):
                report["source_capsule"] = str(input_path)
            return _emit_report(report, json_output=args.json, strict=args.strict)

        if args.command == "cards":
            cards = build_cards(manifest, manifest_path)
            output_dir = Path(args.output_dir).expanduser() if args.output_dir else None
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                paths = {
                    "model": _write_json(output_dir / MODEL_CARD_FILENAME, cards["model"]),
                    "dataset": _write_json(output_dir / DATASET_CARD_FILENAME, cards["dataset"]),
                    "prompt": _write_json(output_dir / PROMPT_CARD_FILENAME, cards["prompt"]),
                    "eval": _write_json(output_dir / EVAL_CARD_FILENAME, cards["eval"]),
                }
                payload: dict[str, Any] = {"schema": "agilab.evidence_cards.v1", "paths": {key: str(path) for key, path in paths.items()}}
            else:
                payload = {"schema": "agilab.evidence_cards.v1", "cards": cards}
            if _is_proof_capsule(input_path):
                payload["source_capsule"] = str(input_path)
            return _emit_report(payload, json_output=args.json, strict=False)

        if args.command == "metadata-store":
            entry = build_metadata_store_entry(manifest, manifest_path)
            if _is_proof_capsule(input_path):
                entry["source_capsule"] = str(input_path)
            store = append_metadata_store(Path(args.store).expanduser(), entry)
            return _emit_report(store, json_output=args.json, strict=False)

    parser.error(f"unsupported command: {args.command}")
    return 2


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build, verify, replay, and export AGILAB evidence manifests."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prove = subparsers.add_parser("prove", help="Write a portable AGILAB proof pack.")
    _add_manifest_argument(prove)
    prove.add_argument("--output-dir", help="Directory for the generated proof pack.")
    prove.add_argument("--export", help="Write a portable .agipack ZIP archive.")
    prove.add_argument("--policy", help="Optional JSON/TOML policy file.")
    prove.add_argument("--metadata-store", help="Append this run to a local metadata store.")
    prove.add_argument("--json", action="store_true", help="Print JSON output.")

    verify = subparsers.add_parser("verify", help="Verify a run manifest.")
    _add_manifest_argument(verify)
    verify.add_argument("--no-artifacts", action="store_true", help="Skip artifact existence checks.")
    verify.add_argument("--strict", action="store_true", help="Exit non-zero when verification fails.")
    verify.add_argument("--json", action="store_true", help="Print JSON output.")

    replay = subparsers.add_parser("replay", help="Print or execute a recorded replay command.")
    _add_manifest_argument(replay)
    replay.add_argument("--execute", action="store_true", help="Actually run the recorded command.")
    replay.add_argument("--timeout", type=float, default=None, help="Timeout when --execute is used.")
    replay.add_argument("--json", action="store_true", help="Print JSON output.")

    export = subparsers.add_parser("export-lineage", help="Export lineage/observability formats.")
    _add_manifest_argument(export)
    export.add_argument(
        "--format",
        choices=("all", "openlineage", "ro-crate", "otel"),
        default="all",
        help="Export format.",
    )
    export.add_argument("--output", help="Output file for a single selected format.")
    export.add_argument("--output-dir", help="Output directory for one or more formats.")
    export.add_argument("--json", action="store_true", help="Print JSON output.")

    traces = subparsers.add_parser("export-traces", help="Export OpenTelemetry-shaped trace JSON.")
    _add_manifest_argument(traces)
    traces.add_argument("--output", help="Output file for the trace JSON.")
    traces.add_argument("--output-dir", help="Output directory for the trace JSON.")
    traces.add_argument("--json", action="store_true", help="Print JSON output.")

    policy = subparsers.add_parser("policy-check", help="Evaluate the manifest against a policy.")
    _add_manifest_argument(policy)
    policy.add_argument("--policy", help="Optional JSON/TOML policy file.")
    policy.add_argument("--strict", action="store_true", help="Exit non-zero when policy fails.")
    policy.add_argument("--json", action="store_true", help="Print JSON output.")

    cards = subparsers.add_parser("cards", help="Generate model/dataset/prompt/eval cards.")
    _add_manifest_argument(cards)
    cards.add_argument("--output-dir", help="Write card files instead of printing them.")
    cards.add_argument("--json", action="store_true", help="Print JSON output.")

    store = subparsers.add_parser("metadata-store", help="Append a run to a local metadata store.")
    _add_manifest_argument(store)
    store.add_argument("--store", required=True, help="Metadata store JSON path.")
    store.add_argument("--json", action="store_true", help="Print JSON output.")
    return parser


def _add_manifest_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "manifest",
        nargs="?",
        help="Path to run_manifest.json. Defaults to the first-proof manifest location.",
    )


def _emit_report(report: Mapping[str, Any], *, json_output: bool, strict: bool) -> int:
    if json_output:
        print(json.dumps(_json_safe(dict(report)), indent=2, sort_keys=True))
    else:
        print(_human_summary(report))
    if strict and str(report.get("status", "pass")) != "pass":
        return 1
    return 0


def _human_summary(report: Mapping[str, Any]) -> str:
    schema = str(report.get("schema", report.get("@context", "agilab.evidence")))
    status = str(report.get("status", "ok"))
    lines = [f"{schema}: {status}"]
    for key in ("manifest_path", "proof_pack_path", "output_dir"):
        if report.get(key):
            lines.append(f"{key}: {report[key]}")
    if isinstance(report.get("checks"), list):
        for check in report["checks"]:
            if isinstance(check, Mapping):
                lines.append(f"- {check.get('id')}: {check.get('status')} - {check.get('summary')}")
    if isinstance(report.get("rules"), list):
        for rule in report["rules"]:
            if isinstance(rule, Mapping):
                lines.append(f"- {rule.get('id')}: {rule.get('status')} - {rule.get('summary')}")
    if isinstance(report.get("paths"), Mapping):
        for key, value in sorted(report["paths"].items()):
            lines.append(f"{key}: {value}")
    return "\n".join(lines)


def _selected_exports(
    manifest: run_manifest.RunManifest,
    manifest_path: Path,
    format_name: str,
) -> dict[str, dict[str, Any]]:
    payloads = {
        "openlineage": build_openlineage_event(manifest, manifest_path),
        "ro-crate": build_ro_crate_metadata(manifest, manifest_path),
        "otel": build_otel_trace_export(manifest, manifest_path),
    }
    if format_name == "all":
        return payloads
    return {format_name: payloads[format_name]}


def _write_selected_exports(
    payloads: Mapping[str, Mapping[str, Any]],
    output: str | None,
    output_dir: str | None,
) -> dict[str, Path]:
    if output and len(payloads) != 1:
        raise ValueError("--output can only be used with a single --format.")
    default_names = {
        "openlineage": OPENLINEAGE_FILENAME,
        "ro-crate": RO_CRATE_FILENAME,
        "otel": OTEL_TRACE_FILENAME,
    }
    paths: dict[str, Path] = {}
    if output:
        key = next(iter(payloads))
        paths[key] = _write_json(Path(output).expanduser(), payloads[key])
        return paths
    directory = Path(output_dir).expanduser() if output_dir else Path.cwd()
    directory.mkdir(parents=True, exist_ok=True)
    for key, payload in payloads.items():
        paths[key] = _write_json(directory / default_names[key], payload)
    return paths


def _check(check_id: str, passed: bool, summary: str, **details: Any) -> dict[str, Any]:
    return {
        "id": check_id,
        "status": "pass" if passed else "fail",
        "summary": summary,
        "details": _json_safe(details),
    }


def _verification_report(
    manifest_path: Path,
    manifest_sha256: str,
    checks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    status = "pass" if checks and all(check.get("status") == "pass" for check in checks) else "fail"
    return {
        "schema": VERIFY_SCHEMA,
        "status": status,
        "manifest_path": str(manifest_path.expanduser()),
        "manifest_sha256": manifest_sha256,
        "checks": [dict(check) for check in checks],
    }


def _capsule_verification_report(
    capsule_path: Path,
    capsule_sha256: str,
    checks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    status = "pass" if checks and all(check.get("status") == "pass" for check in checks) else "fail"
    return {
        "schema": CAPSULE_VERIFY_SCHEMA,
        "status": status,
        "capsule_path": str(capsule_path.expanduser()),
        "capsule_sha256": capsule_sha256,
        "checks": [dict(check) for check in checks],
    }


def _artifact_check(
    artifact: run_manifest.RunManifestArtifact,
    manifest_path: Path,
) -> dict[str, Any]:
    artifact_path = Path(artifact.path).expanduser()
    if not artifact_path.is_absolute():
        artifact_path = manifest_path.parent / artifact_path
    actual_exists = artifact_path.exists()
    should_exist = artifact.exists
    status = "pass" if not should_exist or actual_exists else "fail"
    payload: dict[str, Any] = {
        "id": artifact.name,
        "status": status,
        "path": str(artifact_path),
        "kind": artifact.kind,
        "declared_exists": should_exist,
        "actual_exists": actual_exists,
    }
    if actual_exists and artifact_path.is_file():
        payload["sha256"] = sha256_file(artifact_path)
        payload["size_bytes"] = artifact_path.stat().st_size
    return payload


def _is_proof_capsule(path: Path) -> bool:
    return path.expanduser().suffix.lower() == PROOF_CAPSULE_EXTENSION


def _archive_relative_path(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _sorted_archive_paths(root: Path, paths: Sequence[Path]) -> list[Path]:
    return sorted(paths, key=lambda item: _archive_relative_path(root, item))


def _safe_archive_member_name(name: str) -> bool:
    if not name or name.startswith("/") or name.endswith("/"):
        return False
    candidate = PurePosixPath(name)
    return not candidate.is_absolute() and ".." not in candidate.parts


def _read_archive_json(archive: zipfile.ZipFile, name: str) -> dict[str, Any]:
    payload = json.loads(archive.read(name).decode("utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must contain a JSON object")
    return dict(payload)


def _replay_available(manifest: run_manifest.RunManifest) -> bool:
    if not manifest.command.argv:
        return False
    executable = manifest.command.argv[0]
    if os.sep in executable or (os.altsep and os.altsep in executable):
        return Path(executable).expanduser().exists()
    return shutil.which(executable) is not None


def _has_unredacted_secret_env(manifest: run_manifest.RunManifest) -> bool:
    for key, value in manifest.command.env_overrides.items():
        upper = key.upper()
        secret_like = any(marker in upper for marker in SECRET_ENV_NAMES)
        if secret_like and value and value != "<redacted>":
            return True
    return False


def _artifact_dataset_payload(artifact: run_manifest.RunManifestArtifact) -> dict[str, Any]:
    namespace = "agilab-artifacts"
    path = Path(artifact.path).expanduser()
    name = artifact.name or path.name
    return {
        "namespace": namespace,
        "name": name,
        "facets": {
            "agilab_artifact": {
                "_producer": "https://github.com/ThalesGroup/agilab",
                "_schemaURL": "https://thalesgroup.github.io/agilab/",
                "path": str(path),
                "kind": artifact.kind,
                "exists": artifact.exists,
                "size_bytes": artifact.size_bytes,
            }
        },
    }


def _artifact_ro_id(artifact: run_manifest.RunManifestArtifact) -> str:
    path = Path(artifact.path).expanduser()
    return path.name or artifact.name or "artifact"


def _otel_attr(key: str, value: object) -> dict[str, Any]:
    if isinstance(value, bool):
        return {"key": key, "value": {"boolValue": value}}
    if isinstance(value, int):
        return {"key": key, "value": {"intValue": value}}
    if isinstance(value, float):
        return {"key": key, "value": {"doubleValue": value}}
    return {"key": key, "value": {"stringValue": str(value)}}


def _iso_to_unix_nanos(value: str) -> str:
    if not value:
        return "0"
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return str(int(parsed.timestamp() * 1_000_000_000))
    except ValueError:
        return "0"


def _metadata_value(
    manifest: run_manifest.RunManifest,
    key: str,
    fallback: str,
) -> str:
    for validation in manifest.validations:
        details = validation.details
        value = details.get(key)
        if value:
            return str(value)
    return fallback


def _validation_metrics(manifest: run_manifest.RunManifest) -> dict[str, Any]:
    return {
        "status": manifest.status,
        "validation_count": len(manifest.validations),
        "passed_validation_count": sum(1 for validation in manifest.validations if validation.status == "pass"),
        "duration_seconds": manifest.timing.duration_seconds,
        "target_seconds": manifest.timing.target_seconds,
    }


def _default_policy() -> dict[str, Any]:
    return {
        "schema": "agilab.policy.v1",
        "id": DEFAULT_POLICY_ID,
        "rules": [{"id": rule_id, "required": True} for rule_id in DEFAULT_POLICY_RULES],
    }


def _policy_rule_ids(policy: Mapping[str, Any]) -> tuple[str, ...]:
    rules = policy.get("rules", DEFAULT_POLICY_RULES)
    if isinstance(rules, Mapping):
        return tuple(str(key) for key, enabled in rules.items() if bool(enabled))
    if isinstance(rules, Sequence) and not isinstance(rules, (str, bytes)):
        result = []
        for rule in rules:
            if isinstance(rule, Mapping):
                if rule.get("required", True):
                    result.append(str(rule.get("id", "")))
            else:
                result.append(str(rule))
        return tuple(rule_id for rule_id in result if rule_id)
    raise ValueError("Policy rules must be a mapping or list.")


def _write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(dict(payload)), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_safe(item) for item in value)
    return value


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
