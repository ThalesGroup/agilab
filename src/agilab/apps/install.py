# BSD 3-Clause License
#
# Copyright (c) 2025, Jean-Pierre Morard, THALES SIX GTS France SAS
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this list of conditions and the following disclaimer.
# 2. Redistributions in binary form must reproduce the above copyright notice, this list of conditions and the following disclaimer in the documentation and/or other materials provided with the distribution.
# 3. Neither the name of Jean-Pierre Morard nor the names of its contributors, or THALES SIX GTS France SAS, may be used to endorse or promote products derived from this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES,
# INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.
# IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY,
# OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS;
# OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import argparse
import asyncio
import errno
import getpass
import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

INSTALL_STATE_SCHEMA = "agilab.app_install_state.v2"
INSTALL_STATE_DISABLE_ENV = "AGILAB_DISABLE_APP_INSTALL_CACHE"
INSTALL_STATE_FORCE_ENV = "AGILAB_FORCE_APP_INSTALL"
INSTALL_STATE_CACHE_DIR_ENV = "AGILAB_INSTALL_CACHE_DIR"
FINGERPRINT_SMALL_FILE_LIMIT = 8 * 1024 * 1024
FINGERPRINT_SOURCE_SUFFIXES = {
    ".7z",
    ".csv",
    ".dot",
    ".ipynb",
    ".json",
    ".md",
    ".py",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
FINGERPRINT_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "Modules",
    "build",
    "dist",
}
FINGERPRINT_EXCLUDED_SUFFIXES = {".c", ".pyc", ".pyo", ".pyx", ".so"}


def _package_root() -> Path:
    """Return the installed or source ``agilab`` package directory."""

    return Path(__file__).resolve().parents[1]


def _installed_app_dir_candidates(app_slug: str) -> list[Path]:
    try:
        from agi_env.app_provider_registry import installed_app_project_paths
    except Exception:
        return []

    expected_names = {f"{app_slug}_project", app_slug.replace("-", "_")}
    candidates: list[Path] = []
    for project_root in installed_app_project_paths():
        if project_root.name in expected_names:
            candidates.append(project_root)
    return candidates


def _app_dir_candidates(app_slug: str) -> list[Path]:
    package_root = _package_root()
    candidates = [
        package_root / "apps" / "builtin" / f"{app_slug}_project",
        package_root / "apps" / f"{app_slug}_project",
    ]
    for installed_candidate in _installed_app_dir_candidates(app_slug):
        if installed_candidate not in candidates:
            candidates.append(installed_candidate)
    return candidates


def _inject_source_core_paths(script_path: str | os.PathLike[str], sys_path: list[str]) -> None:
    repo_root = Path(script_path).resolve().parents[3]
    core_root = repo_root / "src" / "agilab" / "core"
    candidates = [
        core_root / "agi-env" / "src",
        core_root / "agi-node" / "src",
        core_root / "agi-cluster" / "src",
        core_root / "agi-core" / "src",
    ]
    for candidate in reversed(candidates):
        if not candidate.exists():
            continue
        path_str = str(candidate)
        if path_str not in sys_path:
            sys_path.insert(0, path_str)


_inject_source_core_paths(__file__, sys.path)
from agi_cluster.agi_distributor import AGI
from agi_env import AgiEnv
from agi_env.runtime_bootstrap_support import default_cluster_share

# Take the first argument from the command line as the module name
if len(sys.argv) > 1:
    project = Path(sys.argv[1])
    project_name = project.name or str(project)
    module = project_name.replace("_project", "").replace('-', '_')
else:
    raise ValueError("Please provide the module name as the first argument.")

module = module.strip().strip("/")
print('install module:', module)


def _seed_example_scripts(app_slug: str) -> None:
    """Copy AGI_* example scripts to ~/log/execute/<app_slug> if missing."""

    if not app_slug:
        return

    examples_dir = _package_root() / "examples" / app_slug
    if not examples_dir.exists():
        return

    execute_dir = Path.home() / "log" / "execute" / app_slug
    logger.info(f"mkdir {execute_dir}")
    execute_dir.mkdir(parents=True, exist_ok=True)

    for source in sorted(examples_dir.glob("AGI_*.py")):
        destination = execute_dir / source.name
        if destination.exists() and not _should_refresh_example_script(destination):
            continue
        try:
            shutil.copy2(source, destination)
            print(f"[INFO] Seeded {destination} from examples.")
        except OSError as exc:
            print(f"[WARN] Unable to copy {source} to {destination}: {exc}")


def _should_refresh_example_script(destination: Path) -> bool:
    """Return True when an existing seeded helper is known-stale."""

    try:
        text = destination.read_text(encoding="utf-8")
    except OSError:
        return False
    return _has_stale_builtin_apps_root(text)


def _has_stale_builtin_apps_root(text: str) -> bool:
    """Detect old built-in helper snippets that missed the ``builtin`` root."""

    stale_marker_root = 'return Path(marker.read_text(encoding="utf-8").strip()) / "apps"'
    current_marker_root = (
        'return Path(marker.read_text(encoding="utf-8").strip()) / "apps" / "builtin"'
    )
    return stale_marker_root in text and current_marker_root not in text


def _seed_lab_stages(app_slug: str) -> None:
    """Copy lab_stages*.toml into ~/export/<app_slug> if missing."""

    if not app_slug:
        return

    app_dir = next((candidate for candidate in _app_dir_candidates(app_slug) if candidate.exists()), None)
    if app_dir is None:
        return

    export_root = Path(os.environ.get("AGI_EXPORT_DIR", Path.home() / "export")).expanduser()
    target_dir = export_root / app_slug
    try:
        logger.info(f"mkdir {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[WARN] Unable to create export dir {target_dir}: {exc}")
        return

    for source in sorted(app_dir.glob("lab_stages*.toml")):
        destination = target_dir / source.name
        if destination.exists():
            continue
        try:
            shutil.copy2(source, destination)
            print(f"[INFO] Seeded {destination} from {source}.")
        except OSError as exc:
            print(f"[WARN] Unable to copy {source} to {destination}: {exc}")

def _seed_app_settings(app_slug: str) -> None:
    """Copy app_settings.toml into ~/export/<app_slug> if missing."""

    if not app_slug:
        return

    project_dir = next((candidate for candidate in _app_dir_candidates(app_slug) if candidate.exists()), None)
    if project_dir is None:
        return
    app_dir = project_dir / "src"
    source = app_dir / "app_settings.toml"
    if not source.exists():
        return

    export_root = Path(os.environ.get("AGI_EXPORT_DIR", Path.home() / "export")).expanduser()
    target_dir = export_root / app_slug
    try:
        logger.info(f"mkdir {target_dir}")
        target_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f"[WARN] Unable to create export dir {target_dir}: {exc}")
        return

    destination = target_dir / "app_settings.toml"
    if destination.exists():
        return
    try:
        shutil.copy2(source, destination)
        print(f"[INFO] Seeded {destination} from {source}.")
    except OSError as exc:
        print(f"[WARN] Unable to copy {source} to {destination}: {exc}")


_seed_example_scripts(module)
_seed_lab_stages(module)
_seed_app_settings(module)


def resolve_share_mount() -> Path:
    """Return the absolute path that AGI_CLUSTER_SHARE should resolve to."""

    share_dir_raw = os.environ.get("AGI_CLUSTER_SHARE")
    share_dir = (
        Path(share_dir_raw)
        if share_dir_raw
        else Path(default_cluster_share(environ=os.environ))
    )
    home_root = Path.home() / "MyApp" if getpass.getuser().startswith("T0") else Path.home()
    share_dir_expanded = share_dir.expanduser()
    if share_dir_expanded.is_absolute():
        return share_dir_expanded
    return (home_root / share_dir_expanded).expanduser()


def ensure_data_storage(env: AgiEnv) -> None:
    """Guarantee the app data directory is available before invoking AGI installers."""

    if env.is_worker_env:
        return
    if not env.app_data_rel:
        raise RuntimeError("App data path is not configured on environment.")
    app_data_path = Path(env.app_data_rel).expanduser()
    share_base = env.share_root_path()
    if app_data_path.is_absolute():
        data_root = app_data_path.resolve(strict=False)
    else:
        data_root = (share_base / app_data_path).resolve(strict=False)
    share_hint = env.agi_share_path
    share_hint_str = str(Path(share_hint).expanduser()) if share_hint else str(share_base)
    try:
        logger.info(f"mkdir {data_root}")
        data_root.mkdir(parents=True, exist_ok=True)
    except FileNotFoundError as exc:
        raise RuntimeError(
            f"Required data directory {data_root} is unavailable. "
            f"Verify AGI_CLUSTER_SHARE ({share_hint_str}) is mounted before running install."
        ) from exc
    except OSError as exc:
        if exc.errno in {
            errno.ENOENT,
            errno.EHOSTDOWN,
            errno.ESTALE,
            errno.ENOTCONN,
            errno.EIO,
        }:
            raise RuntimeError(
                f"Unable to reach data directory {data_root} ({exc.strerror or exc}). "
                f"Verify AGI_CLUSTER_SHARE ({share_hint_str}) is mounted before running install."
            ) from exc
        raise


def validate_app_definition(env: AgiEnv) -> None:
    """Validate that the app has the expected manager/worker sources available."""

    if env.is_worker_env:
        return

    workerless = app_declares_workerless(env)
    missing: list[str] = []
    manager_pyproject = getattr(env, "manager_pyproject", None)
    manager_path = getattr(env, "manager_path", None)
    worker_path = getattr(env, "worker_path", None)

    if isinstance(manager_pyproject, Path) and not manager_pyproject.exists():
        missing.append(f"pyproject={manager_pyproject}")
    if isinstance(manager_path, Path) and not manager_path.exists():
        missing.append(f"manager={manager_path}")
    if not workerless and isinstance(worker_path, Path) and not worker_path.exists():
        missing.append(f"worker={worker_path}")

    if missing:
        target = getattr(env, "app", "<app>")
        target_worker_class = getattr(env, "target_worker_class", "<worker class>")
        contract_hint = (
            "Define the manager module under the app's src/ directory."
            if workerless
            else f"Define {target_worker_class} and the manager module under the app's src/ directory."
        )
        raise RuntimeError(
            f"App '{target}' is missing required sources ({', '.join(missing)}). "
            f"{contract_hint}"
        )

    base_worker_cls = getattr(env, "base_worker_cls", None)
    if not workerless and not base_worker_cls:
        target_worker_class = getattr(env, "target_worker_class", "<worker class>")
        raise RuntimeError(
            f"Unable to determine base worker class for {target_worker_class}. "
            "Ensure the worker inherits from a supported AGI base worker."
        )


def _project_root_from_env_or_path(env_or_path: object) -> Path | None:
    if isinstance(env_or_path, (str, os.PathLike)):
        try:
            return Path(env_or_path)
        except (TypeError, ValueError, RuntimeError):
            return None
    active_app = getattr(env_or_path, "active_app", None)
    if active_app not in (None, ""):
        try:
            return Path(active_app)
        except (TypeError, ValueError, RuntimeError):
            return None
    return None


def app_declares_workerless(env_or_path: object) -> bool:
    """Return whether the app pyproject explicitly opts into manager-only install."""

    project_root = _project_root_from_env_or_path(env_or_path)
    if project_root is None:
        return False
    pyproject = project_root / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    tool = data.get("tool", {})
    agilab = tool.get("agilab", {}) if isinstance(tool, dict) else {}
    app = agilab.get("app", {}) if isinstance(agilab, dict) else {}
    return isinstance(app, dict) and app.get("workerless") is True


def _truthy(value: object) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().strip("\"'").lower() in {"1", "true", "yes", "on"}


def _install_cache_root() -> Path:
    configured = os.environ.get(INSTALL_STATE_CACHE_DIR_ENV)
    if configured:
        return Path(configured).expanduser()
    xdg_cache = os.environ.get("XDG_CACHE_HOME")
    cache_home = Path(xdg_cache).expanduser() if xdg_cache else Path.home() / ".cache"
    return cache_home / "agilab" / "install-state"


def _safe_label(value: object) -> str:
    text = str(value or "app").strip() or "app"
    safe = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text)
    return safe.strip("._-") or "app"


def _path_digest(path: Path) -> str:
    text = str(path.expanduser().resolve(strict=False))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _install_state_path(env: AgiEnv) -> Path:
    active_app = Path(getattr(env, "active_app", "app")).expanduser()
    label = _safe_label(active_app.name or getattr(env, "app", "app"))
    return _install_cache_root() / f"{label}-{_path_digest(active_app)}.json"


def _project_python(project: Path) -> Path:
    if os.name == "nt":
        return project / ".venv" / "Scripts" / "python.exe"
    return project / ".venv" / "bin" / "python"


def _resolved_app_data_root(env: AgiEnv) -> Path | None:
    app_data_rel = getattr(env, "app_data_rel", None)
    if not app_data_rel:
        return None
    app_data_path = Path(app_data_rel).expanduser()
    if app_data_path.is_absolute():
        return app_data_path.resolve(strict=False)
    try:
        share_base = env.share_root_path()
    except (AttributeError, OSError, RuntimeError):
        return None
    return (share_base / app_data_path).resolve(strict=False)


def _dataset_payload_ready(env: AgiEnv) -> tuple[bool, str]:
    dataset_archive = getattr(env, "dataset_archive", None)
    if not isinstance(dataset_archive, Path) or not dataset_archive.exists():
        return True, "no dataset archive"
    data_root = _resolved_app_data_root(env)
    if data_root is None:
        return False, "dataset root unavailable"
    try:
        has_payload = any(path.name != ".DS_Store" for path in data_root.iterdir())
    except OSError:
        return False, f"dataset root unavailable at {data_root}"
    if not has_payload:
        return False, f"dataset payload missing at {data_root}"
    return True, "dataset payload ready"


def _required_install_venvs_ready(env: AgiEnv) -> tuple[bool, str]:
    active_app = Path(getattr(env, "active_app", ""))
    if not _project_python(active_app).exists():
        return False, f"manager venv missing at {active_app / '.venv'}"
    if not app_declares_workerless(env):
        wenv_abs = Path(getattr(env, "wenv_abs", ""))
        if not _project_python(wenv_abs).exists():
            return False, f"worker venv missing at {wenv_abs / '.venv'}"
    dataset_ready, dataset_reason = _dataset_payload_ready(env)
    if not dataset_ready:
        return False, dataset_reason
    return True, "ready"


def _should_scan_file(path: Path) -> bool:
    if path.suffix in FINGERPRINT_EXCLUDED_SUFFIXES:
        return False
    return path.suffix in FINGERPRINT_SOURCE_SUFFIXES


def _iter_fingerprint_files(root: Path) -> list[Path]:
    if not root.exists() or not root.is_dir():
        return []
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        dirnames[:] = sorted(
            dirname
            for dirname in dirnames
            if dirname not in FINGERPRINT_EXCLUDED_DIRS and not dirname.endswith(".egg-info")
        )
        for filename in sorted(filenames):
            path = current / filename
            if _should_scan_file(path):
                files.append(path)
    return files


def _file_fingerprint(base: Path, path: Path) -> dict[str, object]:
    try:
        stat = path.stat()
    except OSError:
        return {"path": path.as_posix(), "missing": True}
    try:
        rel_path = path.relative_to(base).as_posix()
    except ValueError:
        rel_path = path.resolve(strict=False).as_posix()
    record: dict[str, object] = {
        "path": rel_path,
        "size": stat.st_size,
    }
    if stat.st_size <= FINGERPRINT_SMALL_FILE_LIMIT:
        try:
            record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            record["unreadable"] = True
            record["mtime_ns"] = stat.st_mtime_ns
    else:
        record["mtime_ns"] = stat.st_mtime_ns
    return record


def _project_metadata_fingerprints(project: object, label: str) -> list[dict[str, object]]:
    if not isinstance(project, Path):
        return []
    records: list[dict[str, object]] = []
    for filename in ("pyproject.toml", "uv_config.toml", "uv.lock"):
        candidate = project / filename
        if candidate.exists():
            record = _file_fingerprint(project, candidate)
            record["project"] = label
            records.append(record)
    return records


def _uv_version(uv_cmd: object) -> str:
    command = str(uv_cmd or "uv").strip()
    if not command or any(ch.isspace() for ch in command):
        return command
    try:
        completed = subprocess.run(
            [command, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return command
    return (completed.stdout or completed.stderr or command).strip()


def _workerless_uv_sync_command(env: AgiEnv) -> list[str]:
    command = [
        "uv",
        "--preview-features",
        "extra-build-dependencies",
        "sync",
        "--project",
        str(Path(getattr(env, "active_app", "")).expanduser()),
    ]
    python_version = str(getattr(env, "python_version", "") or os.environ.get("AGI_PYTHON_VERSION", "")).strip()
    if python_version:
        command.extend(["-p", python_version])
    return command


def _child_uv_env() -> dict[str, str]:
    child_env = os.environ.copy()
    child_env.pop("UV_RUN_RECURSION_DEPTH", None)
    child_env.pop("VIRTUAL_ENV", None)
    return child_env


def sync_workerless_manager_env(env: AgiEnv) -> None:
    """Install a manager-only app environment without invoking worker deployment."""

    command = _workerless_uv_sync_command(env)
    try:
        completed = subprocess.run(command, check=False, env=_child_uv_env())
    except OSError as exc:
        raise RuntimeError(f"Unable to run workerless app sync command {command!r}: {exc}") from exc
    if completed.returncode != 0:
        raise RuntimeError(f"Workerless app sync failed with exit code {completed.returncode}: {command!r}")


def _compute_install_fingerprint(
    env: AgiEnv,
    *,
    modes_enabled: int,
    scheduler: str,
) -> dict[str, object]:
    active_app = Path(getattr(env, "active_app", "")).expanduser().resolve(strict=False)
    try:
        share_root = env.share_root_path().expanduser().resolve(strict=False).as_posix()
    except (AttributeError, OSError, RuntimeError):
        share_root = ""
    files = [_file_fingerprint(active_app, path) for path in _iter_fingerprint_files(active_app)]
    for label, project in (
        ("agi-env", getattr(env, "agi_env", None)),
        ("agi-node", getattr(env, "agi_node", None)),
        ("agi-core", getattr(env, "agi_core", None)),
        ("agi-cluster", getattr(env, "agi_cluster", None)),
    ):
        files.extend(_project_metadata_fingerprints(project, label))
    payload: dict[str, object] = {
        "schema": INSTALL_STATE_SCHEMA,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": sys.version_info[:3],
        "app": str(getattr(env, "app", "")),
        "target": str(getattr(env, "target", "")),
        "target_worker": str(getattr(env, "target_worker", "")),
        "workerless": app_declares_workerless(env),
        "active_app": active_app.as_posix(),
        "wenv_abs": Path(getattr(env, "wenv_abs", "")).expanduser().resolve(strict=False).as_posix(),
        "app_data_rel": str(getattr(env, "app_data_rel", "")),
        "share_root": share_root,
        "install_type": str(getattr(env, "install_type", "")),
        "is_source_env": bool(getattr(env, "is_source_env", False)),
        "post_install_rel": str(getattr(env, "post_install_rel", "")),
        "python_version": str(getattr(env, "python_version", "")),
        "pyvers_worker": str(getattr(env, "pyvers_worker", "")),
        "uv": str(getattr(env, "uv", "")),
        "uv_worker": str(getattr(env, "uv_worker", "")),
        "uv_version": _uv_version(getattr(env, "uv", "uv")),
        "modes_enabled": int(modes_enabled),
        "scheduler": str(scheduler),
        "files": sorted(files, key=lambda item: (str(item.get("project", "")), str(item.get("path", "")))),
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    payload["digest"] = digest
    return payload


def _install_state_matches(
    env: AgiEnv,
    *,
    modes_enabled: int,
    scheduler: str,
) -> tuple[bool, str]:
    if _truthy(os.environ.get(INSTALL_STATE_DISABLE_ENV)):
        return False, "install cache disabled"
    ready, reason = _required_install_venvs_ready(env)
    if not ready:
        return False, reason
    state_path = _install_state_path(env)
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, f"install state missing at {state_path}"
    if state.get("schema") != INSTALL_STATE_SCHEMA:
        return False, "install state schema changed"
    current = _compute_install_fingerprint(env, modes_enabled=modes_enabled, scheduler=scheduler)
    if state.get("digest") != current.get("digest"):
        return False, "install fingerprint changed"
    return True, "install fingerprint unchanged"


def _write_install_state(
    env: AgiEnv,
    *,
    modes_enabled: int,
    scheduler: str,
) -> None:
    state_path = _install_state_path(env)
    state = _compute_install_fingerprint(env, modes_enabled=modes_enabled, scheduler=scheduler)
    state["written_at"] = time.time()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


async def main():
    """
    Main asynchronous function to resolve paths in pyproject.toml and install a module using AGI.
    """
    try:
        parser = argparse.ArgumentParser(
            description="Run AGILAB application with custom options."
        )

        parser.add_argument(
            "active_app",
            type=str,
            help="Path to the app project (e.g. src/agilab/apps/builtin/flight_telemetry_project)",
        )

        parser.add_argument(
            "--verbose", type=int, default=1, help="Verbosity level (1-3 default: 1)"
        )
        parser.add_argument(
            "--force-install",
            action="store_true",
            help="Run AGI.install even when the local install-state fingerprint is unchanged.",
        )


        argv = [a.replace("$", "") for a in sys.argv[1:]]
        args, unknown = parser.parse_known_args(argv)
        app_path = Path(args.active_app).expanduser()


        try:
            app_env = AgiEnv(
                active_app=app_path,
                verbose=args.verbose,
            )
        except RuntimeError as err:
            share_error_tokens = (
                "Required data directory",
                "Unable to reach data directory",
            )
            if any(token in str(err) for token in share_error_tokens):
                resolved_share = resolve_share_mount()
                share_label = os.environ.get(
                    "AGI_CLUSTER_SHARE",
                    default_cluster_share(environ=os.environ),
                )
                print(
                    "[ERROR] AGI_CLUSTER_SHARE '%s' is not mounted (expected path: %s). "
                    "Mount the share before running install."
                    % (share_label, resolved_share),
                    file=sys.stderr,
                )
                return 2
            raise
    except Exception as e:
        raise Exception("Failed to resolve env and core path in toml") from e

    try:
        ensure_data_storage(app_env)
    except RuntimeError as err:
        print(f"[ERROR] {err}", file=sys.stderr)
        return 1
    try:
        validate_app_definition(app_env)
    except RuntimeError as err:
        print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    scheduler = "127.0.0.1"
    modes_enabled = AGI.DASK_MODE | AGI.CYTHON_MODE
    force_install = args.force_install or _truthy(os.environ.get(INSTALL_STATE_FORCE_ENV))
    if not force_install:
        cache_hit, cache_reason = _install_state_matches(
            app_env,
            modes_enabled=modes_enabled,
            scheduler=scheduler,
        )
        if cache_hit:
            print(
                f"[INFO] Install cache hit for {app_env.active_app}; skipping AGI.install "
                f"({cache_reason})."
            )
            return 0

    if app_declares_workerless(app_env):
        try:
            sync_workerless_manager_env(app_env)
        except RuntimeError as err:
            print(f"[ERROR] {err}", file=sys.stderr)
            return 1
    else:
        await AGI.install(
            env=app_env,
            scheduler=scheduler,
            # scheduler="192.168.20.122",
            # workers={"192.168.20.130":1},
            # workers_data_path="/home/agi/data",
            verbose=args.verbose,
            modes_enabled=modes_enabled,
        )
    try:
        _write_install_state(
            app_env,
            modes_enabled=modes_enabled,
            scheduler=scheduler,
        )
    except OSError as exc:
        print(f"[WARN] Unable to write install-state cache: {exc}", file=sys.stderr)

    local_user = getpass.getuser()
    ssh_user = str(getattr(app_env, "user", "") or "").strip()
    if ssh_user and ssh_user != local_user:
        repo_root = Path(__file__).resolve().parents[3]
        agi_core_dist = repo_root / "src/agilab/core/agi-core/dist"
        install_hint = f"sudo uv add {agi_core_dist}/*.whl"
        print(
            f"[INFO] Current user '{local_user}' differs from cluster SSH user '{ssh_user}'. "
            "Ask the 'agi' login to run:\n"
            "  uv init --bare --no-workspace\n"
            f"  {install_hint}"
        )
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
