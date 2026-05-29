"""Deploy-stage cache, copy-stamp, and timing helpers for local deployment."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

REFRESH_LOCKS_ENV = "AGILAB_REFRESH_LOCKS"
DISABLE_DEPLOY_STAGE_CACHE_ENV = "AGILAB_DISABLE_DEPLOY_STAGE_CACHE"
DEPLOY_STAGE_CACHE_SCHEMA = "agilab-deploy-stage-cache-v1"
DEPLOY_TIMING_TRACE_SCHEMA = "agilab-deploy-timing-v1"
DEPLOY_STAGE_CACHE_HASH_LIMIT = 8 * 1024 * 1024
DEPLOY_COPY_STAMP_SCHEMA = "agilab-deploy-copy-stamp-v1"
DEPLOY_COPY_STAMP_FILENAME = ".agilab-copy-stamp.json"

def _env_value(envars: Any, key: str) -> str | None:
    raw = os.environ.get(key)
    if raw is None:
        try:
            raw = envars.get(key)
        except (AttributeError, RuntimeError, TypeError):
            raw = None
    if raw is None:
        return None
    value = str(raw).strip().strip("\"'").strip()
    return value or None


def _env_truthy(envars: Any, key: str) -> bool:
    raw = _env_value(envars, key)
    if raw is None:
        return False
    return raw.lower() in {"1", "true", "yes", "on"}


def _deploy_stage_cache_enabled(envars: Any) -> bool:
    if _env_truthy(envars, REFRESH_LOCKS_ENV):
        return False
    return not _env_truthy(envars, DISABLE_DEPLOY_STAGE_CACHE_ENV)


def _deploy_stage_cache_path(wenv_abs: Path) -> Path:
    return wenv_abs / ".agilab-stage-cache.json"


def _load_deploy_stage_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    stages = data.get("stages")
    if data.get("schema") != DEPLOY_STAGE_CACHE_SCHEMA or not isinstance(stages, dict):
        return {"schema": DEPLOY_STAGE_CACHE_SCHEMA, "stages": {}}
    return {"schema": DEPLOY_STAGE_CACHE_SCHEMA, "stages": stages}


def _write_deploy_stage_cache(path: Path, state: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "schema": DEPLOY_STAGE_CACHE_SCHEMA,
        "stages": state.get("stages") if isinstance(state.get("stages"), dict) else {},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        return


def _deploy_timing_trace_path(wenv_abs: Path) -> Path:
    return wenv_abs / ".agilab-deploy-timing.json"


def _write_deploy_timing_trace(
    path: Path,
    *,
    stages: list[dict[str, Any]],
    results: dict[str, str],
    app_path: Path,
    worker_project: Path,
) -> None:
    payload = {
        "schema": DEPLOY_TIMING_TRACE_SCHEMA,
        "app_path": _deploy_path_key(app_path),
        "worker_project": _deploy_path_key(worker_project),
        "stages": stages,
        "results": results,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        return


def _deploy_path_key(path: Path) -> str:
    try:
        return path.expanduser().resolve(strict=False).as_posix()
    except (OSError, RuntimeError, ValueError):
        return path.expanduser().as_posix()


def _deploy_stage_file_fingerprint(path: Path) -> dict[str, Any]:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return {"path": _deploy_path_key(path), "missing": True}
    fingerprint: dict[str, Any] = {"path": resolved.as_posix()}
    try:
        stat_result = resolved.stat()
    except OSError:
        fingerprint["missing"] = True
        return fingerprint

    fingerprint["size"] = stat_result.st_size
    if not resolved.is_file():
        fingerprint["kind"] = "directory" if resolved.is_dir() else "other"
        fingerprint["mtime_ns"] = stat_result.st_mtime_ns
        return fingerprint

    if stat_result.st_size > DEPLOY_STAGE_CACHE_HASH_LIMIT:
        fingerprint["mtime_ns"] = stat_result.st_mtime_ns
        return fingerprint

    try:
        fingerprint["sha256"] = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError:
        fingerprint["mtime_ns"] = stat_result.st_mtime_ns
    return fingerprint


def _deploy_stage_directory_fingerprint(root: Path) -> dict[str, Any]:
    try:
        resolved = root.expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return {"path": _deploy_path_key(root), "missing": True}

    fingerprint: dict[str, Any] = {"path": resolved.as_posix()}
    try:
        stat_result = resolved.stat()
    except OSError:
        fingerprint["missing"] = True
        return fingerprint

    if not resolved.is_dir():
        return _deploy_stage_file_fingerprint(resolved)

    fingerprint["kind"] = "directory"
    fingerprint["mtime_ns"] = stat_result.st_mtime_ns
    entries: list[dict[str, Any]] = []
    try:
        children = sorted(
            resolved.rglob("*"), key=lambda candidate: candidate.as_posix()
        )
    except OSError:
        fingerprint["unreadable"] = True
        return fingerprint

    for child in children:
        try:
            relative_path = child.relative_to(resolved).as_posix()
        except ValueError:
            relative_path = child.name
        try:
            if child.is_dir():
                entries.append({"path": relative_path, "kind": "directory"})
            elif child.is_file():
                entries.append(
                    {
                        "path": relative_path,
                        "kind": "file",
                        "fingerprint": _deploy_stage_file_fingerprint(child),
                    }
                )
            else:
                entries.append(
                    {
                        "path": relative_path,
                        "kind": "other",
                        "fingerprint": _deploy_stage_file_fingerprint(child),
                    }
                )
        except OSError:
            entries.append({"path": relative_path, "unreadable": True})
    fingerprint["entries"] = entries
    return fingerprint


def _deploy_copy_stamp_path(output_path: Path, *, directory: bool) -> Path:
    if directory:
        return output_path / DEPLOY_COPY_STAMP_FILENAME
    return output_path.with_name(f".{output_path.name}.agilab-copy-stamp.json")


def _deploy_copy_stamp_payload(
    *,
    kind: str,
    source: Path,
    destination: Path,
    source_fingerprint: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema": DEPLOY_COPY_STAMP_SCHEMA,
        "kind": kind,
        "source": _deploy_path_key(source),
        "destination": _deploy_path_key(destination),
        "source_fingerprint": source_fingerprint,
    }


def _deploy_copy_stamp_matches(
    stamp_path: Path,
    payload: dict[str, Any],
    *,
    output_probe: Callable[[], bool],
) -> bool:
    try:
        stamp = json.loads(stamp_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if stamp != payload:
        return False
    try:
        return output_probe()
    except OSError:
        return False


def _write_deploy_copy_stamp(stamp_path: Path, payload: dict[str, Any]) -> None:
    try:
        stamp_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = stamp_path.with_name(f"{stamp_path.name}.tmp")
        tmp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(stamp_path)
    except OSError:
        return


def _deploy_stage_project_inputs(*projects: Path | None) -> list[Path]:
    inputs: list[Path] = []
    for project in projects:
        if not isinstance(project, Path):
            continue
        inputs.extend(
            [
                project / "pyproject.toml",
                project / "uv.lock",
                project / "uv_config.toml",
                project / "setup.py",
                project / "setup.cfg",
            ]
        )
    return inputs
