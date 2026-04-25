"""Stable run-manifest contract for AGILab evidence surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import platform
from pathlib import Path
import sys
import uuid
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = 1
MANIFEST_KIND = "agilab.run_manifest"
RUN_MANIFEST_FILENAME = "run_manifest.json"
SUPPORTED_STATUSES = {"pass", "fail", "unknown"}


def utc_now() -> str:
    """Return an ISO-8601 UTC timestamp with a stable ``Z`` suffix."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def new_run_id(prefix: str = "run") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@dataclass(frozen=True)
class RunManifestCommand:
    label: str
    argv: tuple[str, ...]
    cwd: str
    env_overrides: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "argv": list(self.argv),
            "cwd": self.cwd,
            "env_overrides": dict(self.env_overrides),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifestCommand":
        return cls(
            label=str(payload.get("label", "")),
            argv=tuple(str(part) for part in payload.get("argv", [])),
            cwd=str(payload.get("cwd", "")),
            env_overrides={
                str(key): str(value)
                for key, value in dict(payload.get("env_overrides", {})).items()
            },
        )


@dataclass(frozen=True)
class RunManifestEnvironment:
    python_version: str
    python_executable: str
    platform: str
    repo_root: str
    active_app: str
    app_name: str

    def as_dict(self) -> dict[str, str]:
        return {
            "python_version": self.python_version,
            "python_executable": self.python_executable,
            "platform": self.platform,
            "repo_root": self.repo_root,
            "active_app": self.active_app,
            "app_name": self.app_name,
        }

    @classmethod
    def from_paths(cls, *, repo_root: Path, active_app: Path) -> "RunManifestEnvironment":
        return cls(
            python_version=platform.python_version(),
            python_executable=sys.executable,
            platform=platform.platform(),
            repo_root=str(repo_root.resolve()),
            active_app=str(active_app.resolve()),
            app_name=active_app.name,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifestEnvironment":
        return cls(
            python_version=str(payload.get("python_version", "")),
            python_executable=str(payload.get("python_executable", "")),
            platform=str(payload.get("platform", "")),
            repo_root=str(payload.get("repo_root", "")),
            active_app=str(payload.get("active_app", "")),
            app_name=str(payload.get("app_name", "")),
        )


@dataclass(frozen=True)
class RunManifestTiming:
    started_at: str
    finished_at: str
    duration_seconds: float
    target_seconds: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "target_seconds": self.target_seconds,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifestTiming":
        target = payload.get("target_seconds")
        return cls(
            started_at=str(payload.get("started_at", "")),
            finished_at=str(payload.get("finished_at", "")),
            duration_seconds=float(payload.get("duration_seconds", 0.0)),
            target_seconds=None if target is None else float(target),
        )


@dataclass(frozen=True)
class RunManifestArtifact:
    name: str
    path: str
    kind: str
    exists: bool
    size_bytes: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "kind": self.kind,
            "exists": self.exists,
            "size_bytes": self.size_bytes,
        }

    @classmethod
    def from_path(
        cls,
        path: Path,
        *,
        name: str | None = None,
        kind: str | None = None,
    ) -> "RunManifestArtifact":
        exists = path.exists()
        size_bytes = path.stat().st_size if exists and path.is_file() else None
        if kind is None:
            kind = "directory" if exists and path.is_dir() else "file"
        return cls(
            name=name or path.name,
            path=str(path.expanduser()),
            kind=kind,
            exists=exists,
            size_bytes=size_bytes,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifestArtifact":
        size = payload.get("size_bytes")
        return cls(
            name=str(payload.get("name", "")),
            path=str(payload.get("path", "")),
            kind=str(payload.get("kind", "")),
            exists=bool(payload.get("exists", False)),
            size_bytes=None if size is None else int(size),
        )


@dataclass(frozen=True)
class RunManifestValidation:
    label: str
    status: str
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "status": self.status,
            "summary": self.summary,
            "details": dict(self.details),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifestValidation":
        return cls(
            label=str(payload.get("label", "")),
            status=str(payload.get("status", "unknown")),
            summary=str(payload.get("summary", "")),
            details=dict(payload.get("details", {})),
        )


@dataclass(frozen=True)
class RunManifest:
    schema_version: int
    kind: str
    run_id: str
    path_id: str
    label: str
    status: str
    command: RunManifestCommand
    environment: RunManifestEnvironment
    timing: RunManifestTiming
    artifacts: tuple[RunManifestArtifact, ...]
    validations: tuple[RunManifestValidation, ...]
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "run_id": self.run_id,
            "path_id": self.path_id,
            "label": self.label,
            "status": self.status,
            "command": self.command.as_dict(),
            "environment": self.environment.as_dict(),
            "timing": self.timing.as_dict(),
            "artifacts": [artifact.as_dict() for artifact in self.artifacts],
            "validations": [validation.as_dict() for validation in self.validations],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RunManifest":
        schema_version = int(payload.get("schema_version", 0))
        kind = str(payload.get("kind", ""))
        status = str(payload.get("status", "unknown"))
        if schema_version != SCHEMA_VERSION:
            raise ValueError(f"Unsupported run manifest schema: {schema_version!r}")
        if kind != MANIFEST_KIND:
            raise ValueError(f"Unsupported run manifest kind: {kind!r}")
        if status not in SUPPORTED_STATUSES:
            raise ValueError(f"Unsupported run manifest status: {status!r}")
        return cls(
            schema_version=schema_version,
            kind=kind,
            run_id=str(payload.get("run_id", "")),
            path_id=str(payload.get("path_id", "")),
            label=str(payload.get("label", "")),
            status=status,
            command=RunManifestCommand.from_dict(dict(payload.get("command", {}))),
            environment=RunManifestEnvironment.from_dict(dict(payload.get("environment", {}))),
            timing=RunManifestTiming.from_dict(dict(payload.get("timing", {}))),
            artifacts=tuple(
                RunManifestArtifact.from_dict(dict(artifact))
                for artifact in payload.get("artifacts", [])
            ),
            validations=tuple(
                RunManifestValidation.from_dict(dict(validation))
                for validation in payload.get("validations", [])
            ),
            created_at=str(payload.get("created_at", "")),
        )


def build_run_manifest(
    *,
    path_id: str,
    label: str,
    status: str,
    command: RunManifestCommand,
    environment: RunManifestEnvironment,
    timing: RunManifestTiming,
    artifacts: Sequence[RunManifestArtifact],
    validations: Sequence[RunManifestValidation],
    run_id: str | None = None,
    created_at: str | None = None,
) -> RunManifest:
    if status not in SUPPORTED_STATUSES:
        raise ValueError(f"Unsupported run manifest status: {status!r}")
    return RunManifest(
        schema_version=SCHEMA_VERSION,
        kind=MANIFEST_KIND,
        run_id=run_id or new_run_id(),
        path_id=path_id,
        label=label,
        status=status,
        command=command,
        environment=environment,
        timing=timing,
        artifacts=tuple(artifacts),
        validations=tuple(validations),
        created_at=created_at or utc_now(),
    )


def run_manifest_path(output_dir: Path) -> Path:
    return output_dir.expanduser() / RUN_MANIFEST_FILENAME


def write_run_manifest(manifest: RunManifest, path: Path) -> Path:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.as_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_run_manifest(path: Path) -> RunManifest:
    return RunManifest.from_dict(json.loads(path.expanduser().read_text(encoding="utf-8")))


def try_load_run_manifest(path: Path) -> tuple[RunManifest | None, str | None]:
    try:
        return load_run_manifest(path), None
    except FileNotFoundError:
        return None, "missing"
    except Exception as exc:
        return None, str(exc)


def manifest_passed(manifest: RunManifest) -> bool:
    return (
        manifest.status == "pass"
        and bool(manifest.validations)
        and all(validation.status == "pass" for validation in manifest.validations)
    )


def manifest_summary(manifest: RunManifest) -> dict[str, Any]:
    return {
        "run_id": manifest.run_id,
        "path_id": manifest.path_id,
        "label": manifest.label,
        "status": manifest.status,
        "duration_seconds": manifest.timing.duration_seconds,
        "target_seconds": manifest.timing.target_seconds,
        "artifact_count": len(manifest.artifacts),
        "validation_statuses": {
            validation.label: validation.status
            for validation in manifest.validations
        },
    }
