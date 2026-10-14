"""Local, content-bound recovery after a notebook provider has terminated.

Checkpoint hashes establish local consistency, not producer authenticity. Only
verification and import may resume; provider commands keep their permanent claims.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import importlib.metadata
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from typing import Iterator

from agilab.agent_runtime.agent_run import _atomic_write_text, validate_agent_run
from agilab.agent_runtime.agent_trace import _try_lock_handle, _unlock_handle
from agilab.evidence.evidence_contract import sha256_file, sha256_payload
from agilab.notebooks.notebook_prerequisites import verify_input_files

CHECKPOINT_FILENAME = "notebook_build_checkpoint.json"
SCHEMA = "agilab.notebook_build_checkpoint.v1"
LOCK_FILENAME = ".notebook_build.lock"
_CACHE_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".git"}
_DERIVED_FILES = {
    "lab_stages.toml",
    "notebook_import.json",
    "results.json",
    "metrics.json",
}
_FIELDS = {
    "schema",
    "created_at",
    "execution_root",
    "project_name",
    "source",
    "prerequisites",
    "protected_files",
    "seconds_before_verification",
    "runtime",
    "provider_manifest",
    "provider_files",
    "project_files",
    "sha256",
}


def _root(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise ValueError(
            "Notebook build root must be an existing directory without a symlink"
        )
    return root.resolve()


def _relative(value: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("Unsafe notebook checkpoint path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("Unsafe notebook checkpoint path")
    return value


def _path(root: Path, relative: str) -> Path:
    path = root
    for part in _relative(relative).split("/"):
        path /= part
        if path.is_symlink():
            raise ValueError(f"Notebook recovery forbids symlinks: {relative}")
    if not path.resolve().is_relative_to(root):
        raise ValueError("Notebook checkpoint path escapes its root")
    return path


def _read_json(path: Path) -> dict:
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"Duplicate notebook checkpoint key: {key}")
            value[key] = item
        return value

    def invalid_constant(value):
        raise ValueError(f"Invalid notebook checkpoint number: {value}")

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=unique,
        parse_constant=invalid_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("Notebook checkpoint JSON must be an object")
    return value


def _snapshot(value: dict | None) -> dict | None:
    if value is not None and not isinstance(value, dict):
        raise ValueError("Notebook checkpoint metadata must be an object")
    return json.loads(json.dumps(value, allow_nan=False))


def _record(root: Path, path: Path) -> dict:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Notebook checkpoint requires a regular file: {path.name}")
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _check_records(records: dict) -> None:
    if not isinstance(records, dict):
        raise ValueError("Notebook checkpoint inventory must be an object")
    for name, descriptor in records.items():
        _relative(name)
        if (
            not isinstance(descriptor, dict)
            or set(descriptor) != {"size_bytes", "sha256"}
            or type(descriptor["size_bytes"]) is not int
            or descriptor["size_bytes"] < 0
            or not isinstance(descriptor["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", descriptor["sha256"]) is None
        ):
            raise ValueError("Notebook checkpoint inventory descriptor is invalid")


def _inventory(root: Path, directory: Path, *, project: bool = False) -> dict:
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(
            f"Notebook recovery directory is missing or unsafe: {directory.name}"
        )
    records = {}

    def walk(current):
        for path in sorted(current.iterdir()):
            if path.is_symlink():
                raise ValueError(
                    f"Notebook recovery forbids symlinks: {path.relative_to(root)}"
                )
            if path.is_dir():
                if not project or path.name not in _CACHE_DIRS:
                    walk(path)
            elif path.is_file():
                if project and path.parent == directory and path.name in _DERIVED_FILES:
                    continue
                entry = _record(root, path)
                records[entry.pop("path")] = entry
            else:
                raise ValueError(
                    f"Notebook recovery forbids special files: {path.relative_to(root)}"
                )

    walk(directory)
    return records


def _runtime() -> dict:
    try:
        version = importlib.metadata.version("agilab")
    except importlib.metadata.PackageNotFoundError:
        version = None
    package = Path(__file__).resolve().parents[1]
    modules = (
        "agent_runtime/notebook_build_checkpoint.py",
        "agent_runtime/notebook_agent.py",
        "agent_runtime/notebook_execution_verifier.py",
        "agent_runtime/notebook_verifier.py",
        "agent_runtime/notebook_workflow_verifier.py",
        "notebooks/notebook_execution_plan.py",
        "notebooks/notebook_pipeline_import.py",
    )
    executable = Path(sys.executable).resolve()
    return {
        "python_executable": str(executable),
        "python_prefix": str(Path(sys.prefix).resolve()),
        "python_base_prefix": str(Path(sys.base_prefix).resolve()),
        "python_sha256": sha256_file(executable),
        "python_version": sys.version,
        "agilab_version": version,
        "implementation_sha256": {
            name: sha256_file(package / name) for name in modules
        },
    }


def _provider(
    root: Path, project: Path, source: dict, manifest: dict
) -> tuple[dict, dict]:
    if (
        not isinstance(manifest, dict)
        or manifest.get("status") != "pass"
        or type(manifest.get("returncode")) is not int
        or manifest["returncode"] != 0
    ):
        raise ValueError(
            "Notebook recovery requires successful terminal provider evidence"
        )
    capture = manifest.get("capture_outcome")
    if (
        not isinstance(capture, dict)
        or type(capture.get("process_returncode")) is not int
        or capture["process_returncode"] != 0
        or "reason" not in capture
        or capture["reason"] is not None
    ):
        raise ValueError(
            "Notebook recovery requires completed provider process capture"
        )
    if not isinstance(manifest.get("run_id"), str) or not manifest["run_id"]:
        raise ValueError("Notebook provider run identifier is missing")
    agent = _path(root, "agent")
    artifacts = manifest.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise ValueError("Notebook provider artifact metadata is invalid")
    paths = {}
    for name in ("manifest", "claim", "stdout", "stderr"):
        entry = artifacts.get(name)
        value = entry.get("path") if isinstance(entry, dict) else entry
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise ValueError(f"Notebook provider {name} path is missing or invalid")
        path = Path(value)
        if not path.is_relative_to(agent):
            raise ValueError("Notebook provider evidence escapes its agent directory")
        paths[name] = _path(root, path.relative_to(root).as_posix())
        if not paths[name].is_file():
            raise ValueError(f"Notebook provider {name} is not a regular file")
        if name != "manifest" and (
            not isinstance(entry, dict)
            or not isinstance(entry.get("sha256"), str)
            or re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is None
            or type(entry.get("size_bytes")) is not int
            or entry["size_bytes"] < 0
        ):
            raise ValueError(
                f"Notebook provider {name} integrity descriptor is incomplete"
            )
    trace = artifacts.get("agent_trace")
    if not isinstance(trace, dict) or not trace.get("exists"):
        raise ValueError("Notebook recovery requires terminal provider trace evidence")
    for name in ("meta", "events", "tool_output_dir"):
        value = trace.get(name)
        if (
            not isinstance(value, str)
            or not Path(value).is_absolute()
            or not Path(value).is_relative_to(agent)
        ):
            raise ValueError("Notebook provider trace escapes its agent directory")
        path = _path(root, Path(value).relative_to(root).as_posix())
        if not (path.is_dir() if name == "tool_output_dir" else path.is_file()):
            raise ValueError("Notebook provider trace evidence is incomplete")
    if _read_json(paths["manifest"]) != manifest:
        raise ValueError("Notebook provider manifest differs from its terminal result")
    command = manifest.get("command", {})
    context = manifest.get("context", {})
    metadata = context.get("metadata", {}) if isinstance(context, dict) else {}
    if not isinstance(command, dict) or not isinstance(metadata, dict):
        raise ValueError("Notebook provider source binding is invalid")
    if (
        command.get("cwd") != str(project)
        or metadata.get("source_sha256") != source["sha256"]
    ):
        raise ValueError(
            "Notebook provider evidence is not bound to this project and source"
        )
    validation = validate_agent_run(manifest)
    if not validation["ok"] or validation["content_integrity"]["status"] != "verified":
        raise ValueError("Notebook provider evidence failed native validation")
    return _record(root, paths["manifest"]), _inventory(root, agent)


def _validate_metadata(root: Path, payload: dict) -> Path:
    name = payload.get("project_name")
    if not isinstance(name, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_-]{0,120}_project", name
    ):
        raise ValueError("Unsafe notebook checkpoint project name")
    if payload.get("execution_root") != str(root):
        raise ValueError("Notebook recovery root changed")
    seconds = payload.get("seconds_before_verification")
    if type(seconds) not in {float, int} or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("Notebook checkpoint duration is invalid")
    source = payload.get("source")
    prerequisites = payload.get("prerequisites")
    if not isinstance(source, dict) or not re.fullmatch(
        r"[0-9a-f]{64}", str(source.get("sha256", ""))
    ):
        raise ValueError("Notebook checkpoint source hash is invalid")
    if prerequisites is not None and not isinstance(prerequisites, dict):
        raise ValueError("Notebook checkpoint prerequisites are invalid")
    project = _path(root, name)
    original = _path(root, f"{name}/source/original.ipynb")
    if sha256_file(original) != source["sha256"]:
        raise ValueError("Notebook original source changed")
    if (
        "license_sha256" in source
        and sha256_file(_path(root, f"{name}/source/LICENSE"))
        != source["license_sha256"]
    ):
        raise ValueError("Notebook original license changed")
    protections = payload.get("protected_files")
    if not isinstance(protections, dict) or not protections:
        raise ValueError("Notebook checkpoint protections are missing")
    for relative, expected in protections.items():
        path = _path(root, relative)
        if (
            not isinstance(expected, str)
            or not re.fullmatch(r"[0-9a-f]{64}", expected)
            or sha256_file(path) != expected
        ):
            raise ValueError(f"Protected notebook build file changed: {relative}")
    if prerequisites is not None:
        if (
            _read_json(_path(root, f"{name}/source/prerequisites.json"))
            != prerequisites
        ):
            raise ValueError("Notebook prerequisites changed")
        verify_input_files(project, prerequisites.get("supplied_inputs", []))
    return project


@contextmanager
def build_lock(root: Path) -> Iterator[None]:
    """Claim the build with an OS lock released on process death; retain its inode."""
    root = _root(root)
    path = _path(root, LOCK_FILENAME)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    handle = os.fdopen(descriptor, "r+b")
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Notebook build lock must be a regular file")
        if not _try_lock_handle(handle):
            raise RuntimeError(
                "Notebook build is already running; inspect its current attempt"
            )
        locked = True
        yield
    finally:
        if locked:
            _unlock_handle(handle)
        handle.close()


def capture_checkpoint(
    root: Path,
    *,
    project_name: str,
    source: dict,
    prerequisites: dict | None,
    provider_manifest: dict,
    protected_files: dict[str, str],
    seconds_before_verification: float,
) -> dict:
    """Freeze trusted controller metadata and a successful provider's exact files."""
    root = _root(root)
    checkpoint = _path(root, CHECKPOINT_FILENAME)
    if checkpoint.exists():
        raise FileExistsError(
            "Notebook build checkpoint already exists; recover its verification"
        )
    payload = {
        "schema": SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_root": str(root),
        "project_name": project_name,
        "source": _snapshot(source),
        "prerequisites": _snapshot(prerequisites),
        "protected_files": _snapshot(protected_files),
        "seconds_before_verification": seconds_before_verification,
    }
    project = _validate_metadata(root, payload)
    payload["provider_manifest"], payload["provider_files"] = _provider(
        root, project, payload["source"], provider_manifest
    )
    payload["project_files"] = _inventory(root, project, project=True)
    payload["runtime"] = _runtime()
    payload["sha256"] = sha256_payload(payload)
    _atomic_write_text(
        checkpoint, json.dumps(payload, indent=2, allow_nan=False) + "\n"
    )
    return payload


def load_checkpoint(root: Path) -> dict:
    """Validate every recovery binding before any generated code executes."""
    root = _root(root)
    payload = _read_json(_path(root, CHECKPOINT_FILENAME))
    if (
        set(payload) not in (_FIELDS, _FIELDS | {"completion_files"})
        or payload.get("schema") != SCHEMA
    ):
        raise ValueError("Unsupported notebook build checkpoint")
    unsealed = {name: value for name, value in payload.items() if name != "sha256"}
    if payload["sha256"] != sha256_payload(unsealed):
        raise ValueError("Notebook build checkpoint changed")
    project = _validate_metadata(root, payload)
    _check_records(payload["project_files"])
    _check_records(payload["provider_files"])
    if payload["runtime"] != _runtime():
        raise ValueError("Notebook recovery runtime or implementation changed")
    descriptor = payload["provider_manifest"]
    if not isinstance(descriptor, dict) or set(descriptor) != {
        "path",
        "sha256",
        "size_bytes",
    }:
        raise ValueError("Notebook provider checkpoint descriptor is invalid")
    path = _path(root, descriptor["path"])
    if _record(root, path) != descriptor:
        raise ValueError("Notebook provider manifest changed")
    manifest_record, provider_files = _provider(
        root, project, payload["source"], _read_json(path)
    )
    if manifest_record != descriptor or provider_files != payload["provider_files"]:
        raise ValueError("Notebook provider evidence inventory changed")
    if _inventory(root, project, project=True) != payload["project_files"]:
        raise ValueError("Notebook generated project inventory changed")
    if "completion_files" in payload:
        _validate_completion(root, payload)
    return payload


def _completion_paths(project_name: str, paths: list[str]) -> None:
    required = {
        "result.json",
        "completion_receipt.json",
        f"{project_name}/lab_stages.toml",
        f"{project_name}/notebook_import.json",
    }
    if len(set(paths)) != len(paths) or not required.issubset(paths):
        raise ValueError(
            "Notebook completion seal requires its result, receipt and persisted import"
        )
    log_names = set()
    recovery_attempts = set()
    recovery_reports = set()
    recovery_claims = set()
    for name in paths:
        _relative(name)
        if name in required | {
            f"{project_name}/results.json",
            f"{project_name}/metrics.json",
        }:
            continue
        if name in {"verification.log", "workflow_verification.log"}:
            log_names.add(name)
        else:
            match = re.fullmatch(
                r"notebook_recovery_attempts/([A-Za-z0-9][A-Za-z0-9_-]{0,120})/"
                r"(notebook_verification\.log|notebook_workflow_verification\.log|notebook_recovery_result\.json|notebook_recovery_attempt\.json)",
                name,
            )
            if match is None:
                raise ValueError(
                    "Notebook completion seal contains an unsupported file"
                )
            attempt, role = match.groups()
            recovery_attempts.add(attempt)
            if role == "notebook_recovery_result.json":
                recovery_reports.add(attempt)
            elif role == "notebook_recovery_attempt.json":
                recovery_claims.add(attempt)
            else:
                log_names.add(role.removeprefix("notebook_"))
    if log_names != {"verification.log", "workflow_verification.log"}:
        raise ValueError(
            "Notebook completion seal requires both independent verification logs"
        )
    if recovery_attempts and (
        len(recovery_attempts) != 1
        or recovery_reports != recovery_attempts
        or recovery_claims != recovery_attempts
        or "verification.log" in paths
        or "workflow_verification.log" in paths
    ):
        raise ValueError(
            "Notebook completion seal must bind one recovery attempt and its report"
        )


def _validate_completion(root: Path, payload: dict) -> None:
    records = payload["completion_files"]
    _check_records(records)
    _completion_paths(payload["project_name"], list(records))
    for name, expected in records.items():
        actual = _record(root, _path(root, name))
        actual.pop("path")
        if actual != expected:
            raise ValueError(f"Notebook completion evidence changed: {name}")
    report = _read_json(_path(root, "result.json"))
    receipt = _read_json(_path(root, "completion_receipt.json"))
    if (
        report.get("status") != "passed"
        or receipt.get("status") != "passed"
        or report.get("project") != str(root / payload["project_name"])
    ):
        raise ValueError(
            "Notebook completion seal does not describe this successful build"
        )
    for name in records:
        if name.startswith("notebook_recovery_attempts/") and name.endswith(
            "/notebook_recovery_result.json"
        ):
            if _read_json(_path(root, name)).get("status") != "passed":
                raise ValueError(
                    "Notebook recovery completion report does not describe a pass"
                )


def seal_completion(root: Path, completion_files: list[str]) -> None:
    """Bind a successful report, receipt, verification logs and persisted workflow."""
    root = _root(root)
    payload = load_checkpoint(root)
    if "completion_files" in payload:
        raise FileExistsError("Notebook completion evidence is already sealed")
    if not isinstance(completion_files, list) or any(
        not isinstance(name, str) for name in completion_files
    ):
        raise ValueError("Notebook completion file list is invalid")
    _completion_paths(payload["project_name"], completion_files)
    records = {}
    for name in completion_files:
        record = _record(root, _path(root, name))
        records[record.pop("path")] = record
    payload["completion_files"] = records
    _validate_completion(root, payload)
    payload["sha256"] = sha256_payload(
        {k: v for k, v in payload.items() if k != "sha256"}
    )
    _atomic_write_text(
        _path(root, CHECKPOINT_FILENAME),
        json.dumps(payload, indent=2, allow_nan=False) + "\n",
    )
