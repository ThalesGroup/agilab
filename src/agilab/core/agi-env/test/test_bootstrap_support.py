from __future__ import annotations

import importlib.util
from types import SimpleNamespace

import pytest

from agi_env.bootstrap_support import (
    can_link_repo_apps,
    coerce_active_app_request,
    resolve_active_app_selection,
    resolve_builtin_apps_path,
    resolve_default_apps_path,
    resolve_install_type,
    resolve_package_dir,
    resolve_requested_apps_path,
)


def test_coerce_active_app_request_accepts_legacy_alias(tmp_path):
    app, override = coerce_active_app_request(None, {"active_app": tmp_path / "demo_project"})

    assert app == "demo_project"
    assert override == tmp_path / "demo_project"


def test_resolve_install_type_detects_worker_and_source_layouts(tmp_path):
    worker_root = tmp_path / "wenv" / "demo_worker"
    worker_root.mkdir(parents=True)
    source_root = tmp_path / "repo" / "src" / "agilab" / "apps"
    source_root.mkdir(parents=True)

    assert resolve_install_type(worker_root)[0] == 2
    assert resolve_install_type(source_root)[0] == 1
    assert resolve_install_type(None, active_app_override=tmp_path / "apps" / "demo_project")[0] == 1


def test_resolve_requested_apps_path_prefers_env_then_override(tmp_path):
    env_apps = tmp_path / "env-apps"
    env_apps.mkdir()
    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path=str(env_apps),
        explicit_apps_path=None,
        active_app_override=None,
    )
    assert apps_path == env_apps.resolve()
    assert builtin_root is None

    builtin_app = tmp_path / "apps" / "builtin" / "demo_project"
    builtin_app.mkdir(parents=True)
    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path="",
        explicit_apps_path=None,
        active_app_override=builtin_app,
    )
    assert apps_path == builtin_app.parent.parent.resolve()
    assert builtin_root == builtin_app.parent.resolve()


def test_resolve_builtin_default_and_active_app_selection(tmp_path):
    repo_root = tmp_path / "repo"
    agilab_pck = tmp_path / "site" / "agilab"
    builtin_root = agilab_pck / "apps" / "builtin"
    builtin_root.mkdir(parents=True)

    assert resolve_builtin_apps_path(apps_path=None, repo_root=repo_root, agilab_pck=agilab_pck) == builtin_root

    default_apps_root = tmp_path / "default-apps"
    repo_apps = tmp_path / "repo-apps"
    repo_apps.mkdir()
    apps_path, apps_repository_root = resolve_default_apps_path(
        apps_path=None,
        is_worker_env=False,
        default_apps_root=default_apps_root,
        apps_repository_root=repo_apps,
    )
    assert apps_path == repo_apps
    assert apps_repository_root == repo_apps

    builtin_app = repo_apps / "builtin" / "demo_project"
    builtin_app.mkdir(parents=True)
    selection = resolve_active_app_selection(
        app="demo_project",
        active_app_override=None,
        apps_path=repo_apps,
        builtin_apps_path=builtin_app.parent,
        home_abs=tmp_path / "home",
        is_worker_env=False,
        default_app="flight_project",
    )
    assert selection.app == "demo_project"
    assert selection.active_app == builtin_app


def test_can_link_repo_apps_rejects_builtin_and_nested_project_roots(tmp_path):
    apps_root = tmp_path / "apps"
    builtin_root = apps_root / "builtin"
    builtin_app = builtin_root / "demo_project"
    builtin_app.mkdir(parents=True)
    project_root = apps_root / "demo_project"
    project_root.mkdir(parents=True)

    assert can_link_repo_apps(
        apps_path=apps_root,
        active_app=builtin_app,
        builtin_apps_path=builtin_root,
        is_worker_env=False,
        skip_repo_links=False,
    ) is False
    assert can_link_repo_apps(
        apps_path=project_root,
        active_app=project_root,
        builtin_apps_path=builtin_root,
        is_worker_env=False,
        skip_repo_links=False,
    ) is False


def test_resolve_package_dir_uses_search_locations_then_origin(monkeypatch, tmp_path):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    origin_file = pkg_dir / "__init__.py"
    origin_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(origin_file), submodule_search_locations=[str(pkg_dir)]) if name == "demo" else None,
    )
    assert resolve_package_dir("demo") == pkg_dir.resolve()

    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    with pytest.raises(ModuleNotFoundError):
        resolve_package_dir("missing")
