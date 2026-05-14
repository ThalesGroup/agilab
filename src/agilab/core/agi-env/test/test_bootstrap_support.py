from __future__ import annotations

import importlib.util
from pathlib import Path
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


def test_coerce_active_app_request_preserves_explicit_app_and_handles_bad_path_cls():
    kwargs = {"active_app": object()}
    app, override = coerce_active_app_request("explicit-app", kwargs)
    assert app == "explicit-app"
    assert override is None
    assert "active_app" in kwargs

    class _BrokenPath:
        def __call__(self, _value):
            raise TypeError("bad path")

    kwargs = {"active_app": 7}
    app, override = coerce_active_app_request(None, kwargs, path_cls=_BrokenPath())
    assert app == "7"
    assert override is None
    assert "active_app" not in kwargs


def test_resolve_install_type_detects_worker_and_source_layouts(tmp_path):
    worker_root = tmp_path / "wenv" / "demo_worker"
    worker_root.mkdir(parents=True)
    source_root = tmp_path / "repo" / "src" / "agilab" / "apps"
    source_root.mkdir(parents=True)

    assert resolve_install_type(worker_root)[0] == 2
    assert resolve_install_type(source_root)[0] == 1
    assert resolve_install_type(None, active_app_override=tmp_path / "apps" / "demo_project")[0] == 1


def test_resolve_install_type_handles_default_worker_and_path_errors(tmp_path):
    assert resolve_install_type(None) == (2, True)
    assert resolve_install_type(tmp_path / "custom-apps") == (0, False)

    class _BrokenAppsPath:
        def resolve(self):
            raise RuntimeError("resolve bug")

    assert resolve_install_type(_BrokenAppsPath()) == (0, False)


def test_resolve_requested_apps_path_prefers_explicit_apps_path_over_env(tmp_path):
    env_apps = tmp_path / "agi-space" / "apps"
    explicit_apps = tmp_path / "agilab-src" / "src" / "agilab" / "apps"
    env_apps.mkdir(parents=True)
    explicit_apps.mkdir(parents=True)

    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path=str(env_apps),
        explicit_apps_path=explicit_apps,
        active_app_override=None,
    )

    assert apps_path == explicit_apps.resolve()
    assert builtin_root is None


def test_resolve_requested_apps_path_uses_env_when_no_explicit_root(tmp_path):
    env_apps = tmp_path / "env-apps"
    env_apps.mkdir()
    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path=str(env_apps),
        explicit_apps_path=None,
        active_app_override=None,
    )
    assert apps_path == env_apps.resolve()
    assert builtin_root is None


def test_resolve_requested_apps_path_prefers_absolute_active_override_over_env(tmp_path):
    env_apps = tmp_path / "agi-space" / "apps"
    env_apps.mkdir(parents=True)
    builtin_app = tmp_path / "apps" / "builtin" / "demo_project"
    builtin_app.mkdir(parents=True)

    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path=str(env_apps),
        explicit_apps_path=None,
        active_app_override=builtin_app,
    )

    assert apps_path == builtin_app.parent.parent.resolve()
    assert builtin_root == builtin_app.parent.resolve()


def test_resolve_requested_apps_path_handles_explicit_missing_and_active_override_fallback(tmp_path):
    explicit_apps = tmp_path / "missing-apps"
    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path="",
        explicit_apps_path=explicit_apps,
        active_app_override=None,
    )
    assert apps_path == explicit_apps
    assert builtin_root is None

    class _BrokenParentPath(type(Path())):
        def resolve(self):
            raise OSError("resolve bug")

    active_app_override = _BrokenParentPath(tmp_path / "apps" / "demo_project")
    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path="",
        explicit_apps_path=None,
        active_app_override=active_app_override,
    )
    assert apps_path == active_app_override.parent
    assert builtin_root is None

    assert resolve_requested_apps_path(
        env_apps_path="",
        explicit_apps_path=None,
        active_app_override=None,
    ) == (None, None)


def test_resolve_requested_apps_path_handles_resolve_errors_via_custom_path_cls(tmp_path):
    class _BrokenExpandPath:
        def __init__(self, value):
            self.value = value

        def expanduser(self):
            return self

        def resolve(self):
            raise OSError("resolve bug")

    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path="~/apps",
        explicit_apps_path=None,
        active_app_override=None,
        path_cls=_BrokenExpandPath,
    )
    assert isinstance(apps_path, _BrokenExpandPath)
    assert builtin_root is None

    class _BrokenExplicitPath(_BrokenExpandPath):
        def resolve(self):
            raise FileNotFoundError("missing")

    apps_path, builtin_root = resolve_requested_apps_path(
        env_apps_path="",
        explicit_apps_path=tmp_path / "explicit-apps",
        active_app_override=None,
        path_cls=_BrokenExplicitPath,
    )
    assert isinstance(apps_path, _BrokenExplicitPath)
    assert builtin_root is None


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
        default_app="flight_telemetry_project",
    )
    assert selection.app == "demo_project"
    assert selection.active_app == builtin_app


def test_resolve_builtin_apps_path_prefers_existing_candidates(tmp_path):
    apps_builtin = tmp_path / "apps" / "builtin"
    apps_builtin.mkdir(parents=True)
    repo_root = tmp_path / "repo"
    agilab_pck = tmp_path / "site" / "agilab"
    assert resolve_builtin_apps_path(apps_path=apps_builtin, repo_root=repo_root, agilab_pck=agilab_pck) == apps_builtin

    apps_root = tmp_path / "apps-root"
    (apps_root / "builtin").mkdir(parents=True)
    assert resolve_builtin_apps_path(apps_path=apps_root, repo_root=repo_root, agilab_pck=agilab_pck) == apps_root / "builtin"

    repo_builtin = repo_root / "apps" / "builtin"
    repo_builtin.mkdir(parents=True)
    assert resolve_builtin_apps_path(apps_path=None, repo_root=repo_root, agilab_pck=agilab_pck) == repo_builtin

    assert resolve_builtin_apps_path(apps_path=None, repo_root=tmp_path / "missing-repo", agilab_pck=tmp_path / "missing-pkg") is None


def test_resolve_default_apps_path_covers_default_root_and_passthrough(tmp_path):
    apps_root = tmp_path / "apps"
    repo_root = tmp_path / "repo-apps"
    repo_root.mkdir()
    default_root = tmp_path / "default-root"
    default_root.mkdir()

    assert resolve_default_apps_path(
        apps_path=apps_root,
        is_worker_env=False,
        default_apps_root=default_root,
        apps_repository_root=repo_root,
    ) == (apps_root, repo_root)

    assert resolve_default_apps_path(
        apps_path=None,
        is_worker_env=True,
        default_apps_root=default_root,
        apps_repository_root=repo_root,
    ) == (None, repo_root)

    assert resolve_default_apps_path(
        apps_path=None,
        is_worker_env=False,
        default_apps_root=default_root,
        apps_repository_root=repo_root,
    ) == (default_root, repo_root)

    assert resolve_default_apps_path(
        apps_path=None,
        is_worker_env=False,
        default_apps_root=default_root,
        apps_repository_root=None,
    ) == (default_root, None)


def test_resolve_active_app_selection_covers_worker_defaults_override_and_builtin_fallback(tmp_path):
    with pytest.raises(ValueError, match="app is required when self.is_worker_env"):
        resolve_active_app_selection(
            app=None,
            active_app_override=None,
            apps_path=None,
            builtin_apps_path=None,
            home_abs=tmp_path / "home",
            is_worker_env=True,
            default_app="demo_project",
        )

    worker = resolve_active_app_selection(
        app="demo_worker",
        active_app_override=None,
        apps_path=None,
        builtin_apps_path=None,
        home_abs=tmp_path / "home",
        is_worker_env=True,
        default_app="demo_project",
    )
    assert worker.active_app == tmp_path / "home" / "wenv" / "demo_worker"

    override = tmp_path / "custom-app"
    override.mkdir()
    selected = resolve_active_app_selection(
        app=None,
        active_app_override=override,
        apps_path=tmp_path / "apps",
        builtin_apps_path=None,
        home_abs=tmp_path / "home",
        is_worker_env=False,
        default_app="",
    )
    assert selected.app == "flight_telemetry_project"
    assert selected.active_app == override

    builtin_root = tmp_path / "apps" / "builtin"
    builtin_root.mkdir(parents=True)
    builtin_app = builtin_root / "chosen_project"
    builtin_app.mkdir()
    selected = resolve_active_app_selection(
        app="chosen_project",
        active_app_override=tmp_path / "missing-override",
        apps_path=tmp_path / "apps",
        builtin_apps_path=builtin_root,
        home_abs=tmp_path / "home",
        is_worker_env=False,
        default_app="demo_project",
    )
    assert selected.active_app == builtin_app


def test_resolve_active_app_selection_handles_base_dir_and_builtin_resolution_errors(tmp_path):
    class _BrokenResolvePath(type(Path())):
        def resolve(self):
            raise OSError("resolve bug")

    apps_path = _BrokenResolvePath(tmp_path / "apps")
    selected = resolve_active_app_selection(
        app="demo_project",
        active_app_override=None,
        apps_path=apps_path,
        builtin_apps_path=_BrokenResolvePath(tmp_path / "builtin"),
        home_abs=tmp_path / "home",
        is_worker_env=False,
        default_app="demo_project",
    )
    assert selected.active_app == apps_path / "demo_project"


def test_resolve_active_app_selection_covers_no_builtin_path_and_builtin_exists_error(tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    selected = resolve_active_app_selection(
        app="demo_project",
        active_app_override=None,
        apps_path=apps_root,
        builtin_apps_path=None,
        home_abs=tmp_path / "home",
        is_worker_env=False,
        default_app="demo_project",
    )
    assert selected.active_app == apps_root.resolve() / "demo_project"

    class _BrokenExistsPath(type(Path())):
        def exists(self):
            raise OSError("exists bug")

    selected = resolve_active_app_selection(
        app="demo_project",
        active_app_override=None,
        apps_path=apps_root,
        builtin_apps_path=_BrokenExistsPath(tmp_path / "builtin"),
        home_abs=tmp_path / "home",
        is_worker_env=False,
        default_app="demo_project",
    )
    assert selected.active_app == apps_root.resolve() / "demo_project"


def test_resolve_active_app_selection_uses_installed_app_project_provider(tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    installed_project = tmp_path / "site-packages" / "agi_app_flight_telemetry" / "project" / "flight_telemetry_project"
    installed_project.mkdir(parents=True)
    (installed_project / "pyproject.toml").write_text("[project]\nname='flight_telemetry_project'\n", encoding="utf-8")

    selected = resolve_active_app_selection(
        app="flight_telemetry_project",
        active_app_override=None,
        apps_path=apps_root,
        builtin_apps_path=None,
        installed_app_projects=(installed_project,),
        home_abs=tmp_path / "home",
        is_worker_env=False,
        default_app="demo_project",
    )

    assert selected.active_app == installed_project.resolve()


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


def test_can_link_repo_apps_covers_early_exit_errors_and_positive_case(tmp_path):
    apps_root = tmp_path / "apps"
    apps_root.mkdir()
    active_app = apps_root / "demo_project"
    active_app.mkdir()

    assert can_link_repo_apps(
        apps_path=None,
        active_app=active_app,
        builtin_apps_path=None,
        is_worker_env=False,
        skip_repo_links=False,
    ) is False
    assert can_link_repo_apps(
        apps_path=apps_root,
        active_app=active_app,
        builtin_apps_path=None,
        is_worker_env=True,
        skip_repo_links=False,
    ) is False
    assert can_link_repo_apps(
        apps_path=apps_root,
        active_app=active_app,
        builtin_apps_path=None,
        is_worker_env=False,
        skip_repo_links=True,
    ) is False

    class _BrokenResolvePath(type(Path())):
        def resolve(self, *args, **kwargs):
            raise OSError("resolve bug")

    broken_apps = _BrokenResolvePath(apps_root)
    broken_active = _BrokenResolvePath(active_app)
    assert can_link_repo_apps(
        apps_path=broken_apps,
        active_app=broken_active,
        builtin_apps_path=_BrokenResolvePath(tmp_path / "builtin"),
        is_worker_env=False,
        skip_repo_links=False,
    ) is True

    keep_root = tmp_path / "keep-root"
    keep_root.mkdir()
    keep_app = keep_root / "demo"
    keep_app.mkdir()
    assert can_link_repo_apps(
        apps_path=keep_root,
        active_app=keep_app,
        builtin_apps_path=None,
        is_worker_env=False,
        skip_repo_links=False,
    ) is True

    worker_root = tmp_path / "node_worker"
    worker_root.mkdir()
    worker_app = worker_root / "demo"
    worker_app.mkdir()
    assert can_link_repo_apps(
        apps_path=worker_root,
        active_app=worker_app,
        builtin_apps_path=None,
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


def test_resolve_package_dir_handles_spec_errors_empty_locations_and_missing_origin(monkeypatch, tmp_path):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()
    origin_file = pkg_dir / "__init__.py"
    origin_file.write_text("", encoding="utf-8")

    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: (_ for _ in ()).throw(ModuleNotFoundError("boom")))
    with pytest.raises(ModuleNotFoundError):
        resolve_package_dir("missing")

    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: (_ for _ in ()).throw(ValueError("boom")))
    with pytest.raises(ModuleNotFoundError):
        resolve_package_dir("missing")

    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(origin=str(origin_file), submodule_search_locations=["", str(tmp_path / "missing-loc")]),
    )
    assert resolve_package_dir("demo") == pkg_dir.resolve()

    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda _name: SimpleNamespace(origin=str(tmp_path / "missing-origin" / "__init__.py"), submodule_search_locations=None),
    )
    with pytest.raises(ModuleNotFoundError):
        resolve_package_dir("demo")


def test_resolve_package_dir_uses_explicit_find_spec_and_missing_origin_value(tmp_path):
    pkg_dir = tmp_path / "pkg"
    pkg_dir.mkdir()

    def _find_spec(_name):
        return SimpleNamespace(origin=None, submodule_search_locations=[str(tmp_path / "missing")])

    with pytest.raises(ModuleNotFoundError):
        resolve_package_dir("demo", find_spec_fn=_find_spec)
