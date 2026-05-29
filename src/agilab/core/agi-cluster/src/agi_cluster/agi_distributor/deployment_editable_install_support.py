"""Editable install cache helpers for local deployment virtualenvs."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from agi_cluster.agi_distributor.deployment_stage_cache_support import (
    _deploy_stage_file_fingerprint,
)
from agi_cluster.agi_distributor.deployment_venv_support import (
    project_site_packages_dir as _project_site_packages_dir,
    project_venv_cfg_version as _project_venv_cfg_version,
    project_venv_python as _project_venv_python,
    project_venv_root as _project_venv_root,
)

EDITABLE_INSTALL_CACHE_SCHEMA = "agilab-editable-install-cache-v1"


def _is_python_project(path: Path) -> bool:
    return (path / "pyproject.toml").exists() or (path / "setup.py").exists()


def _editable_install_cache_path(venv_project: Path) -> Path:
    resolved_project = venv_project.expanduser().resolve(strict=False)
    cache_key = hashlib.sha256(
        json.dumps(
            {
                "schema": EDITABLE_INSTALL_CACHE_SCHEMA,
                "venv_project": resolved_project.as_posix(),
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return (
        resolved_project.parent
        / ".agilab-editable-install-cache"
        / f"{resolved_project.name}-{cache_key}.json"
    )


def _load_editable_install_cache(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    installs = data.get("installs")
    if data.get("schema") != EDITABLE_INSTALL_CACHE_SCHEMA or not isinstance(
        installs, dict
    ):
        return {"schema": EDITABLE_INSTALL_CACHE_SCHEMA, "installs": {}}
    return {"schema": EDITABLE_INSTALL_CACHE_SCHEMA, "installs": installs}


def _write_editable_install_cache(path: Path, state: dict[str, Any]) -> None:
    payload: dict[str, Any] = {
        "schema": EDITABLE_INSTALL_CACHE_SCHEMA,
        "installs": state.get("installs")
        if isinstance(state.get("installs"), dict)
        else {},
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


def _editable_install_project(package_ref: str | Path) -> Path | None:
    try:
        package_path = Path(package_ref).expanduser()
    except (OSError, TypeError, ValueError):
        return None
    return package_path if _is_python_project(package_path) else None


def _editable_install_proof_exists(
    venv_project: Path,
    package_project: Path,
    *,
    os_name: str = os.name,
    python_version: str | None = None,
) -> bool:
    site_packages = _project_site_packages_dir(
        venv_project,
        os_name=os_name,
        python_version=python_version,
    )
    if not site_packages.exists():
        return False

    expected_path = package_project.expanduser().resolve(strict=False)
    try:
        direct_url_files = sorted(site_packages.glob("*.dist-info/direct_url.json"))
    except OSError:
        return False

    for direct_url_file in direct_url_files:
        try:
            data = json.loads(direct_url_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        dir_info = data.get("dir_info")
        if not isinstance(dir_info, dict) or dir_info.get("editable") is not True:
            continue
        raw_url = data.get("url")
        if not isinstance(raw_url, str):
            continue
        parsed = urlparse(raw_url)
        if parsed.scheme != "file":
            continue
        if parsed.netloc and parsed.netloc not in {"localhost", "127.0.0.1"}:
            continue
        raw_path = unquote(parsed.path)
        # On Windows ``file:///C:/...`` urlparses to ``/C:/...``; the leading
        # slash breaks ``Path()`` so we strip it when a drive letter follows.
        if (
            os_name == "nt"
            and len(raw_path) >= 3
            and raw_path[0] == "/"
            and raw_path[2] == ":"
        ):
            raw_path = raw_path[1:]
        installed_path = Path(raw_path).resolve(strict=False)
        if installed_path == expected_path:
            return True
    return False


def _editable_install_metadata_inputs(package_project: Path) -> list[Path]:
    return [
        package_project / "pyproject.toml",
        package_project / "setup.py",
        package_project / "setup.cfg",
    ]


def _editable_install_cache_key(
    *,
    package_project: Path,
    venv_project: Path,
) -> str:
    payload = {
        "schema": EDITABLE_INSTALL_CACHE_SCHEMA,
        "package_project": package_project.expanduser()
        .resolve(strict=False)
        .as_posix(),
        "venv": _project_venv_root(venv_project).resolve(strict=False).as_posix(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _editable_install_digest(
    *,
    uv_cmd: str,
    package_project: Path,
    venv_project: Path,
    editable: bool,
    no_deps: bool,
    python_version: str | None,
    os_name: str,
) -> str:
    payload = {
        "schema": EDITABLE_INSTALL_CACHE_SCHEMA,
        "uv_cmd": uv_cmd.strip(),
        "package_project": package_project.expanduser()
        .resolve(strict=False)
        .as_posix(),
        "venv": _project_venv_root(venv_project).resolve(strict=False).as_posix(),
        "venv_python": _project_venv_python(venv_project, os_name=os_name)
        .resolve(strict=False)
        .as_posix(),
        "python_version": str(python_version or ""),
        "venv_cfg_version": _project_venv_cfg_version(venv_project),
        "editable": bool(editable),
        "no_deps": bool(no_deps),
        "os_name": os_name,
        "metadata": [
            _deploy_stage_file_fingerprint(path)
            for path in _editable_install_metadata_inputs(package_project)
        ],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def _editable_install_cache_hit(
    *,
    uv_cmd: str,
    package_project: Path,
    venv_project: Path,
    editable: bool,
    no_deps: bool,
    python_version: str | None,
    os_name: str,
) -> bool:
    cache_path = _editable_install_cache_path(venv_project)
    state = _load_editable_install_cache(cache_path)
    installs = state.get("installs")
    if not isinstance(installs, dict):
        return False

    key = _editable_install_cache_key(
        package_project=package_project,
        venv_project=venv_project,
    )
    cached = installs.get(key)
    if not isinstance(cached, dict):
        return False
    digest = _editable_install_digest(
        uv_cmd=uv_cmd,
        package_project=package_project,
        venv_project=venv_project,
        editable=editable,
        no_deps=no_deps,
        python_version=python_version,
        os_name=os_name,
    )
    return cached.get("digest") == digest and _editable_install_proof_exists(
        venv_project,
        package_project,
        os_name=os_name,
        python_version=python_version,
    )


def _record_editable_install_cache(
    *,
    uv_cmd: str,
    package_project: Path,
    venv_project: Path,
    editable: bool,
    no_deps: bool,
    python_version: str | None,
    os_name: str,
) -> None:
    if not _editable_install_proof_exists(
        venv_project,
        package_project,
        os_name=os_name,
        python_version=python_version,
    ):
        return
    cache_path = _editable_install_cache_path(venv_project)
    state = _load_editable_install_cache(cache_path)
    installs = state.setdefault("installs", {})
    if not isinstance(installs, dict):
        return
    key = _editable_install_cache_key(
        package_project=package_project,
        venv_project=venv_project,
    )
    installs[key] = {
        "digest": _editable_install_digest(
            uv_cmd=uv_cmd,
            package_project=package_project,
            venv_project=venv_project,
            editable=editable,
            no_deps=no_deps,
            python_version=python_version,
            os_name=os_name,
        )
    }
    _write_editable_install_cache(cache_path, state)
