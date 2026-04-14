from __future__ import annotations

from pathlib import Path

from agi_env.runtime_bootstrap_support import (
    parse_int_env_value,
    resolve_share_runtime_config,
    sync_repository_apps,
)


def test_parse_int_env_value_falls_back_for_blank_and_invalid():
    assert parse_int_env_value({"TABLE_MAX_ROWS": ""}, "TABLE_MAX_ROWS", 100) == 100
    assert parse_int_env_value({"TABLE_MAX_ROWS": "bad"}, "TABLE_MAX_ROWS", 100) == 100
    assert parse_int_env_value({"TABLE_MAX_ROWS": "42"}, "TABLE_MAX_ROWS", 100) == 42


def test_sync_repository_apps_links_missing_projects(tmp_path):
    apps_path = tmp_path / "apps"
    apps_path.mkdir()
    repo_apps = tmp_path / "repo-apps"
    project = repo_apps / "alpha_project"
    project.mkdir(parents=True)
    linked: list[tuple[Path, Path, bool]] = []

    sync_repository_apps(
        can_link_repo=True,
        apps_path=apps_path,
        apps_root=tmp_path / "packaged-apps",
        active_app=apps_path / "demo_project",
        is_source_env=False,
        apps_repository_root=repo_apps,
        get_apps_repository_root_fn=lambda: repo_apps,
        ensure_dir_fn=lambda path: path.mkdir(parents=True, exist_ok=True),
        copy_existing_projects_fn=lambda *_args: None,
        create_symlink_windows_fn=lambda *_args: None,
        symlink_fn=lambda src, dst, target_is_directory=False: linked.append((src, dst, target_is_directory)),
        logger=None,
        os_name="posix",
    )

    assert linked == [(project, apps_path / "alpha_project", True)]


def test_sync_repository_apps_falls_back_to_copy_when_repo_source_missing(tmp_path):
    copied: list[tuple[Path, Path]] = []
    apps_path = tmp_path / "apps"
    active_app = apps_path / "demo_project"
    apps_root = tmp_path / "packaged-apps"
    apps_root.mkdir()

    sync_repository_apps(
        can_link_repo=True,
        apps_path=apps_path,
        apps_root=apps_root,
        active_app=active_app,
        is_source_env=False,
        apps_repository_root=None,
        get_apps_repository_root_fn=lambda: None,
        ensure_dir_fn=lambda _path: None,
        copy_existing_projects_fn=lambda src, dst: copied.append((src, dst)),
        create_symlink_windows_fn=lambda *_args: None,
        logger=None,
        os_name="posix",
    )

    assert copied == [(apps_root, active_app.parent)]


def test_resolve_share_runtime_config_applies_share_dir_override(tmp_path):
    envars = {"AGI_SHARE_DIR": "cluster_mount"}

    result = resolve_share_runtime_config(
        envars=envars,
        environ={},
        is_worker_env=False,
        resolve_workspace_settings_fn=lambda: None,
        find_source_settings_fn=lambda: None,
        clean_envar_value_fn=lambda *_args, **_kwargs: "cluster_mount",
        resolve_cluster_enabled_fn=lambda **_kwargs: True,
        resolve_runtime_share_path_fn=lambda **kwargs: kwargs["cluster_share"],
        env_path=tmp_path / ".env",
        home_path=tmp_path,
    )

    assert result.local_share == "localshare"
    assert result.cluster_share == "cluster_mount"
    assert result.agi_share_path == "cluster_mount"
    assert envars["AGI_CLUSTER_SHARE"] == "cluster_mount"
