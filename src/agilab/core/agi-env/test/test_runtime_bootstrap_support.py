from __future__ import annotations

from pathlib import Path

import pytest

from agi_env.runtime_bootstrap_support import (
    default_cluster_share,
    default_share_user,
    parse_int_env_value,
    resolve_share_runtime_config,
    sync_repository_apps,
)


def test_parse_int_env_value_falls_back_for_blank_and_invalid():
    assert parse_int_env_value({"TABLE_MAX_ROWS": ""}, "TABLE_MAX_ROWS", 100) == 100
    assert parse_int_env_value({"TABLE_MAX_ROWS": "bad"}, "TABLE_MAX_ROWS", 100) == 100
    assert parse_int_env_value({"TABLE_MAX_ROWS": "42"}, "TABLE_MAX_ROWS", 100) == 42


def test_default_cluster_share_is_user_scoped_and_filesystem_safe():
    environ = {"USER": "alice@example.com"}

    assert default_share_user(environ=environ) == "alice_example.com"
    assert default_cluster_share(environ=environ) == "clustershare/alice_example.com"
    assert default_cluster_share(environ={}) == "clustershare/user"


def test_resolve_share_runtime_config_defaults_cluster_share_per_user(tmp_path):
    result = resolve_share_runtime_config(
        envars={},
        environ={"USER": "demo-user"},
        is_worker_env=False,
        resolve_workspace_settings_fn=lambda: None,
        find_source_settings_fn=lambda: None,
        clean_envar_value_fn=lambda *_args, **_kwargs: None,
        resolve_cluster_enabled_fn=lambda **_kwargs: True,
        resolve_runtime_share_path_fn=lambda **kwargs: kwargs["cluster_share"],
        env_path=tmp_path / ".env",
        home_path=tmp_path,
    )

    assert result.cluster_share == "clustershare/demo-user"
    assert result.agi_share_path == "clustershare/demo-user"


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


def test_sync_repository_apps_links_projects_in_sorted_order_when_glob_varies(tmp_path, monkeypatch):
    apps_path = tmp_path / "apps"
    apps_path.mkdir()
    repo_apps = tmp_path / "repo-apps"
    alpha = repo_apps / "alpha_project"
    zeta = repo_apps / "zeta_project"
    alpha.mkdir(parents=True)
    zeta.mkdir(parents=True)
    linked: list[tuple[Path, Path, bool]] = []

    real_glob = Path.glob

    def _fake_glob(self: Path, pattern: str):
        if self == repo_apps and pattern == "*_project":
            return iter([zeta, alpha])
        return real_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", _fake_glob)

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

    assert linked == [
        (alpha, apps_path / "alpha_project", True),
        (zeta, apps_path / "zeta_project", True),
    ]


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


def test_sync_repository_apps_covers_noop_windows_and_copy_fallback_exceptions(tmp_path):
    apps_path = tmp_path / "apps"
    apps_path.mkdir()
    repo_apps = tmp_path / "repo-apps"
    repo_apps.mkdir()
    project = repo_apps / "alpha_project"
    project.mkdir()
    linked: list[tuple[Path, Path]] = []
    copied: list[tuple[Path, Path]] = []

    sync_repository_apps(
        can_link_repo=False,
        apps_path=apps_path,
        apps_root=tmp_path / "packaged-apps",
        active_app=apps_path / "demo_project",
        is_source_env=False,
        apps_repository_root=repo_apps,
        get_apps_repository_root_fn=lambda: repo_apps,
        ensure_dir_fn=lambda path: (_ for _ in ()).throw(AssertionError("should not ensure")),
        copy_existing_projects_fn=lambda *_args: copied.append(_args),
        create_symlink_windows_fn=lambda *_args: linked.append(_args[:2]),
        logger=None,
        os_name="posix",
    )
    assert linked == []
    assert copied == []

    sync_repository_apps(
        can_link_repo=True,
        apps_path=apps_path,
        apps_root=tmp_path / "packaged-apps",
        active_app=apps_path / "demo_project",
        is_source_env=False,
        apps_repository_root=repo_apps,
        get_apps_repository_root_fn=lambda: repo_apps,
        ensure_dir_fn=lambda _path: None,
        copy_existing_projects_fn=lambda *_args: None,
        create_symlink_windows_fn=lambda src, dst: linked.append((src, dst)),
        logger=None,
        os_name="nt",
    )
    assert linked == [(project, apps_path / "alpha_project")]

    copied.clear()
    apps_root = tmp_path / "packaged-apps"
    apps_root.mkdir()

    sync_repository_apps(
        can_link_repo=True,
        apps_path=apps_path,
        apps_root=apps_root,
        active_app=apps_path / "demo_project",
        is_source_env=False,
        apps_repository_root=None,
        get_apps_repository_root_fn=lambda: None,
        ensure_dir_fn=lambda _path: None,
        copy_existing_projects_fn=lambda src, dst: (_ for _ in ()).throw(OSError("copy failed")),
        create_symlink_windows_fn=lambda *_args: None,
        logger=None,
        os_name="posix",
    )


def test_sync_repository_apps_handles_same_tree_and_dest_resolve_failures(tmp_path):
    apps_path = tmp_path / "apps"
    apps_path.mkdir()
    repo_apps = tmp_path / "repo-apps"
    repo_apps.mkdir()
    project = repo_apps / "alpha_project"
    project.mkdir()
    existing_dest = apps_path / "alpha_project"
    existing_dest.mkdir()
    original_resolve = Path.resolve

    def _patched_resolve(self, strict=False):
        if self in {apps_path, existing_dest}:
            raise OSError("resolve failed")
        return original_resolve(self, strict=strict)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(Path, "resolve", _patched_resolve, raising=False)
    try:
        sync_repository_apps(
            can_link_repo=True,
            apps_path=apps_path,
            apps_root=tmp_path / "packaged-apps",
            active_app=apps_path / "demo_project",
            is_source_env=False,
            apps_repository_root=repo_apps,
            get_apps_repository_root_fn=lambda: repo_apps,
            ensure_dir_fn=lambda _path: None,
            copy_existing_projects_fn=lambda *_args: None,
            create_symlink_windows_fn=lambda *_args: None,
            symlink_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("should not symlink")),
            logger=None,
            os_name="posix",
        )
    finally:
        monkeypatch.undo()


def test_sync_repository_apps_skips_probe_errors_and_logs_created_symlink(tmp_path, monkeypatch):
    apps_path = tmp_path / "apps"
    apps_path.mkdir()
    repo_apps = tmp_path / "repo-apps"
    repo_apps.mkdir()
    blocked_project = repo_apps / "blocked_project"
    linked_project = repo_apps / "linked_project"
    blocked_project.mkdir()
    linked_project.mkdir()
    linked = []
    infos = []

    blocked_dest = apps_path / "blocked_project"
    original_exists = Path.exists

    def _patched_exists(self):
        if self == blocked_dest:
            raise OSError("probe failed")
        return original_exists(self)

    monkeypatch.setattr(Path, "exists", _patched_exists, raising=False)

    sync_repository_apps(
        can_link_repo=True,
        apps_path=apps_path,
        apps_root=tmp_path / "packaged-apps",
        active_app=apps_path / "demo_project",
        is_source_env=False,
        apps_repository_root=repo_apps,
        get_apps_repository_root_fn=lambda: repo_apps,
        ensure_dir_fn=lambda _path: None,
        copy_existing_projects_fn=lambda *_args: None,
        create_symlink_windows_fn=lambda *_args: None,
        symlink_fn=lambda src, dst, target_is_directory=False: linked.append((src, dst, target_is_directory)),
        logger=type("Logger", (), {"info": lambda self, *args: infos.append(args)})(),
        os_name="posix",
    )

    assert (linked_project, apps_path / "linked_project", True) in linked
    assert infos and "Created symbolic link for app: %s -> %s" in infos[0][0]


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


def test_resolve_share_runtime_config_ignores_unsettable_override(tmp_path):
    class _BrokenEnvars(dict):
        def __setitem__(self, key, value):
            raise TypeError("immutable")

    result = resolve_share_runtime_config(
        envars=_BrokenEnvars({"AGI_SHARE_DIR": "cluster_mount"}),
        environ={"AGI_LOCAL_SHARE": "local", "AGI_CLUSTER_SHARE": "cluster"},
        is_worker_env=False,
        resolve_workspace_settings_fn=lambda: None,
        find_source_settings_fn=lambda: None,
        clean_envar_value_fn=lambda *_args, **_kwargs: "cluster_mount",
        resolve_cluster_enabled_fn=lambda **_kwargs: False,
        resolve_runtime_share_path_fn=lambda **kwargs: kwargs["local_share"],
        env_path=tmp_path / ".env",
        home_path=tmp_path,
    )

    assert result.local_share == "local"
    assert result.cluster_share == "cluster_mount"
    assert result.agi_share_path == "local"
