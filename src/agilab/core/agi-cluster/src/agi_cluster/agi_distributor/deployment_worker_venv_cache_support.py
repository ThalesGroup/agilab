import hashlib
import json
import os
import platform
import re
from pathlib import Path
from typing import Any

from agi_cluster.agi_distributor.deployment_stage_cache_support import (
    _env_truthy,
    _env_value,
)


SHARED_WORKER_VENV_ENV = "AGILAB_SHARED_WORKER_VENV"
SHARED_WORKER_VENV_DIR_ENV = "AGILAB_SHARED_WORKER_VENV_DIR"


def _file_fingerprint(path: Path) -> dict[str, Any]:
    try:
        return {
            "path": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    except OSError:
        return {"path": path.name, "missing": True}


def _shared_worker_venv_cache_key(
    *,
    active_app: Path,
    wenv_abs: Path,
    python_version: str,
    run_type: Any,
    options_worker: str,
    worker_core_add_specs: list[str],
    hw_rapids_capable: bool,
) -> str:
    payload = {
        "schema": "agilab-worker-venv-v1",
        "os_name": os.name,
        "platform": platform.system(),
        "machine": platform.machine(),
        "python_version": str(python_version),
        "run_type": str(run_type),
        "options_worker": options_worker.strip(),
        "hw_rapids_capable": bool(hw_rapids_capable),
        "active_app": str(active_app.resolve(strict=False)),
        "worker_pyproject": _file_fingerprint(wenv_abs / "pyproject.toml"),
        "worker_uv_config": _file_fingerprint(wenv_abs / "uv_config.toml"),
        "app_pyproject": _file_fingerprint(active_app / "pyproject.toml"),
        "app_uv_config": _file_fingerprint(active_app / "uv_config.toml"),
        "worker_core_add_specs": sorted(str(spec) for spec in worker_core_add_specs),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    py_label = (
        re.sub(r"[^A-Za-z0-9_.-]+", "_", str(python_version)).strip("._-") or "python"
    )
    platform_label = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "_",
        f"{platform.system().lower()}-{platform.machine().lower()}",
    ).strip("._-")
    return f"py{py_label}-{platform_label}-{digest}"


def _shared_worker_venv_project(
    envars: Any,
    *,
    active_app: Path,
    wenv_abs: Path,
    python_version: str,
    run_type: Any,
    options_worker: str,
    worker_core_add_specs: list[str],
    hw_rapids_capable: bool,
) -> Path | None:
    if not _env_truthy(envars, SHARED_WORKER_VENV_ENV):
        return None

    raw_root = _env_value(envars, SHARED_WORKER_VENV_DIR_ENV)
    if raw_root:
        cache_root = Path(raw_root).expanduser()
        if not cache_root.is_absolute():
            cache_root = (wenv_abs.parent / cache_root).resolve(strict=False)
    else:
        cache_root = wenv_abs.parent / ".runtime-cache"

    cache_key = _shared_worker_venv_cache_key(
        active_app=active_app,
        wenv_abs=wenv_abs,
        python_version=python_version,
        run_type=run_type,
        options_worker=options_worker,
        worker_core_add_specs=worker_core_add_specs,
        hw_rapids_capable=hw_rapids_capable,
    )
    return cache_root / cache_key
