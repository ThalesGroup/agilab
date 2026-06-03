"""Runtime bootstrap helpers extracted from AgiEnv constructor."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ShareRuntimeConfig:
    local_share: str
    cluster_share: str
    agi_share_path: str


def default_share_user(*, environ) -> str:
    """Return the filesystem-safe user segment used by default share paths."""
    raw_user = (
        environ.get("AGILAB_SHARE_USER")
        or environ.get("USER")
        or environ.get("USERNAME")
        or "user"
    )
    safe_user = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(raw_user)).strip("_")
    return safe_user or "user"


def default_cluster_share(*, environ) -> str:
    """Return the per-user fallback cluster share root."""
    return f"clustershare/{default_share_user(environ=environ)}"


def parse_int_env_value(envars: dict, key: str, default: int) -> int:
    """Parse an integer env/config value with a defensive default."""
    try:
        return int(str(envars.get(key, default) or "").strip() or default)
    except (TypeError, ValueError):
        return default


def sync_repository_apps(
    *,
    can_link_repo: bool,
    apps_path: Path | None,
    apps_root: Path,
    active_app: Path,
    is_source_env: bool,
    apps_repository_root: Path | None,
    get_apps_repository_root_fn,
    ensure_dir_fn,
    copy_existing_projects_fn,
    create_symlink_windows_fn,
    symlink_fn=os.symlink,
    logger=None,
    os_name: str | None = None,
    path_cls=Path,
) -> None:
    """Link or copy repo apps into the working apps root when the layout allows it."""
    if not can_link_repo or apps_path is None:
        return

    ensure_dir_fn(apps_path)
    link_source = apps_repository_root or get_apps_repository_root_fn()

    if link_source is not None and link_source.exists():
        same_tree = False
        try:
            same_tree = apps_path.resolve(strict=False) == link_source.resolve()
        except OSError:
            same_tree = False

        if not same_tree:
            for src_app in sorted(link_source.glob("*_project"), key=lambda candidate: candidate.name):
                dest_app = apps_path / src_app.relative_to(link_source)
                try:
                    if dest_app.exists() or dest_app.resolve(strict=False) == src_app.resolve():
                        continue
                except OSError:
                    continue

                if (os_name or os.name) == "nt":
                    create_symlink_windows_fn(path_cls(src_app), dest_app)
                else:
                    symlink_fn(src_app, dest_app, target_is_directory=True)
                if logger is not None:
                    logger.info("Created symbolic link for app: %s -> %s", src_app, dest_app)
        return

    if apps_root.exists() and not is_source_env:
        try:
            if apps_root.resolve() != active_app.parent.resolve():
                copy_existing_projects_fn(apps_root, active_app.parent)
        except OSError:
            pass


def resolve_share_runtime_config(
    *,
    envars,
    environ,
    is_worker_env: bool,
    resolve_workspace_settings_fn,
    find_source_settings_fn,
    clean_envar_value_fn,
    resolve_cluster_enabled_fn,
    resolve_runtime_share_path_fn,
    env_path,
    home_path,
) -> ShareRuntimeConfig:
    """Resolve local/cluster share settings and the effective runtime share path."""
    local_share = envars.get("AGI_LOCAL_SHARE") or environ.get("AGI_LOCAL_SHARE") or "localshare"
    cluster_share = (
        envars.get("AGI_CLUSTER_SHARE")
        or environ.get("AGI_CLUSTER_SHARE")
        or default_cluster_share(environ=environ)
    )

    share_dir_override = clean_envar_value_fn(envars, "AGI_CLUSTER_SHARE", fallback_to_process=True)
    if share_dir_override is not None:
        cluster_share = share_dir_override
        try:
            envars["AGI_CLUSTER_SHARE"] = share_dir_override
        except TypeError:
            pass

    cluster_enabled = resolve_cluster_enabled_fn(
        is_worker_env=is_worker_env,
        resolve_workspace_settings_fn=resolve_workspace_settings_fn,
        find_source_settings_fn=find_source_settings_fn,
        envars=envars,
        environ=environ,
    )
    agi_share_path = resolve_runtime_share_path_fn(
        cluster_share=cluster_share,
        local_share=local_share,
        cluster_enabled=bool(cluster_enabled),
        env_path=env_path,
        home_path=home_path,
    )
    return ShareRuntimeConfig(
        local_share=local_share,
        cluster_share=cluster_share,
        agi_share_path=agi_share_path,
    )
