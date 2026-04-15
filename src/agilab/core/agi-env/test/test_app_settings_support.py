from pathlib import Path

import pytest

import agi_env.app_settings_support as app_settings_module


def test_app_settings_aliases_and_candidate_paths(tmp_path: Path):
    assert app_settings_module.app_settings_aliases("demo_project") == {"demo_project", "demo_worker"}
    assert app_settings_module.app_settings_aliases("demo_worker") == {"demo_worker", "demo_project"}
    assert app_settings_module.app_settings_aliases("demo_project_worker") == {
        "demo_project",
        "demo_project_worker",
    }
    assert app_settings_module.app_settings_aliases(None) == set()

    src_dir = tmp_path / "demo_project" / "src"
    src_dir.mkdir(parents=True)
    src_settings = src_dir / "app_settings.toml"
    src_settings.write_text("[cluster]\ncluster_enabled = false\n", encoding="utf-8")

    assert app_settings_module.candidate_app_settings_path(src_dir) == src_settings
    assert app_settings_module.candidate_app_settings_path(src_dir.parent) == src_settings
    assert app_settings_module.candidate_app_settings_path(object()) is None


def test_candidate_app_settings_path_handles_probe_oserror_and_propagates_runtime_bug(tmp_path: Path, monkeypatch):
    src_dir = tmp_path / "demo_project" / "src"
    src_dir.mkdir(parents=True)
    src_settings = src_dir / "app_settings.toml"

    original_is_file = Path.is_file

    def _oserror_is_file(self):
        if self == src_settings:
            raise OSError("probe failed")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", _oserror_is_file, raising=False)
    assert app_settings_module.candidate_app_settings_path(src_dir.parent) == src_settings

    def _runtime_is_file(self):
        if self == src_settings:
            raise RuntimeError("probe bug")
        return original_is_file(self)

    monkeypatch.setattr(Path, "is_file", _runtime_is_file, raising=False)
    with pytest.raises(RuntimeError, match="probe bug"):
        app_settings_module.candidate_app_settings_path(src_dir.parent)


def test_find_source_and_user_app_settings_cover_workspace_seed_paths(tmp_path: Path):
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    resources_path = home_abs / ".agilab"
    resources_path.mkdir(parents=True)

    active_app = tmp_path / "apps" / "demo_project"
    active_src = active_app / "src"
    active_src.mkdir(parents=True)
    source_settings = active_src / "app_settings.toml"
    source_settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")

    found = app_settings_module.find_source_app_settings_file(
        target_app="demo_worker",
        current_app="demo_project",
        app_src=active_src,
        active_app=active_app,
        apps_path=tmp_path / "apps",
        builtin_apps_path=None,
        apps_repository_root=None,
        home_abs=home_abs,
        envars={},
    )
    assert found == source_settings

    workspace_file = app_settings_module.resolve_user_app_settings_file(
        target_app="demo_project",
        resources_path=resources_path,
        find_source_file=lambda _app_name=None: found,
    )
    assert workspace_file.exists()
    assert workspace_file.read_text(encoding="utf-8") == source_settings.read_text(encoding="utf-8")

    touched = app_settings_module.resolve_user_app_settings_file(
        target_app="blank_project",
        resources_path=tmp_path / "resources",
        ensure_exists=True,
        find_source_file=lambda _app_name=None: None,
    )
    assert touched.exists()
    assert touched.read_text(encoding="utf-8") == ""

    unresolved = app_settings_module.resolve_user_app_settings_file(
        target_app="blank_project",
        resources_path=tmp_path / "resources",
        ensure_exists=False,
        find_source_file=lambda _app_name=None: None,
    )
    assert unresolved == tmp_path / "resources" / "apps" / "blank_project" / "app_settings.toml"


def test_app_settings_source_roots_collect_aliases_repo_builtin_worker_and_export(tmp_path: Path):
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    app_src = tmp_path / "current" / "demo_project" / "src"
    app_src.mkdir(parents=True)
    active_app = app_src.parent
    apps_path = tmp_path / "apps"
    apps_path.mkdir()
    builtin_apps_path = tmp_path / "apps" / "builtin"
    builtin_apps_path.mkdir(parents=True)
    repo_root = tmp_path / "repo-apps"
    repo_root.mkdir()

    roots = app_settings_module.app_settings_source_roots(
        target_app="demo_worker",
        current_app="demo_project",
        app_src=app_src,
        active_app=active_app,
        apps_path=apps_path,
        builtin_apps_path=builtin_apps_path,
        apps_repository_root=repo_root,
        home_abs=home_abs,
        envars={"AGI_EXPORT_DIR": "export-root"},
    )
    roots_set = set(roots)

    assert app_src in roots_set
    assert active_app in roots_set
    assert active_app / "src" in roots_set
    assert apps_path / "demo_worker" in roots_set
    assert apps_path / "demo_project" in roots_set
    assert builtin_apps_path / "demo_worker" in roots_set
    assert builtin_apps_path / "demo_project" in roots_set
    assert repo_root in roots_set
    assert repo_root / "demo_worker" in roots_set
    assert repo_root / "demo_project" in roots_set
    assert home_abs / "wenv" / "demo_worker" in roots_set
    assert home_abs / "wenv" / "demo_project" in roots_set
    assert home_abs / "export-root" in roots_set
    assert home_abs / "export-root" / "demo_project" in roots_set


def test_app_settings_source_roots_handles_export_oserror_and_propagates_runtime_bug(tmp_path: Path, monkeypatch):
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    original_expanduser = Path.expanduser

    def _export_oserror(self):
        if self == Path("export-root"):
            raise OSError("export probe failed")
        return original_expanduser(self)

    monkeypatch.setattr(Path, "expanduser", _export_oserror, raising=False)
    roots = app_settings_module.app_settings_source_roots(
        target_app="demo_project",
        current_app=None,
        app_src=None,
        active_app=None,
        apps_path=None,
        builtin_apps_path=None,
        apps_repository_root=None,
        home_abs=home_abs,
        envars={"AGI_EXPORT_DIR": "export-root"},
    )
    assert home_abs / "wenv" / "demo_project" in set(roots)
    assert home_abs / "export-root" not in set(roots)

    def _export_runtime(self):
        if self == Path("export-root"):
            raise RuntimeError("export bug")
        return original_expanduser(self)

    monkeypatch.setattr(Path, "expanduser", _export_runtime, raising=False)
    with pytest.raises(RuntimeError, match="export bug"):
        app_settings_module.app_settings_source_roots(
            target_app="demo_project",
            current_app=None,
            app_src=None,
            active_app=None,
            apps_path=None,
            builtin_apps_path=None,
            apps_repository_root=None,
            home_abs=home_abs,
            envars={"AGI_EXPORT_DIR": "export-root"},
        )


def test_resolve_user_app_settings_requires_target_name(tmp_path: Path):
    with pytest.raises(RuntimeError, match="without an app name"):
        app_settings_module.resolve_user_app_settings_file(
            target_app=None,
            resources_path=tmp_path / ".agilab",
            find_source_file=lambda _app_name=None: None,
        )
