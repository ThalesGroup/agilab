from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from agi_env import (
    agi_logger,
    credential_store_support,
    package_layout_support,
    pagelib_data_support,
    pagelib_execution_support,
    pagelib_preview_support,
    pagelib_project_support,
    pagelib_selection_support,
    project_clone_support,
    share_mount_support,
    share_runtime_support,
    worker_runtime_support,
)


def _dummy_worker_env(tmp_path: Path, *, app_name: str = "demo_project") -> SimpleNamespace:
    active_app = tmp_path / "apps" / app_name
    (active_app / "src").mkdir(parents=True, exist_ok=True)
    agi_root = tmp_path / "site-packages" / "agilab"
    node_pck = agi_root / "core" / "agi-node" / "src" / "agi_node"
    node_pck.mkdir(parents=True, exist_ok=True)
    target = app_name.replace("_project", "").replace("_worker", "")
    target_worker = f"{target}_worker"
    worker_path = active_app / "src" / target_worker / f"{target_worker}.py"
    return SimpleNamespace(
        app=app_name,
        active_app=active_app,
        builtin_apps_path=None,
        agilab_pck=agi_root,
        node_pck=node_pck,
        is_worker_env=False,
        app_src=active_app / "src",
        uv="uv",
        target=target,
        target_worker=target_worker,
        worker_path=worker_path,
        worker_pyproject=worker_path.parent / "pyproject.toml",
        dataset_archive=worker_path.parent / "dataset.7z",
        wenv_abs=tmp_path / "home" / "wenv" / target_worker,
        _collect_pythonpath_entries=lambda: ["PYTHONPATH-entry"],
        _configure_pythonpath=lambda _entries: None,
        _ensure_repository_app_link=lambda: False,
        copy_existing_projects=lambda *_args, **_kwargs: None,
        has_agilab_anywhere_under_home=lambda _path: False,
    )


def test_worker_runtime_support_covers_remaining_builtin_and_copy_fallbacks(tmp_path: Path, monkeypatch):
    logger = mock.Mock()

    env_bad_app = _dummy_worker_env(tmp_path)
    env_bad_app.app = object()
    worker_runtime_support._resolve_builtin_worker_paths(
        env_bad_app,
        target="demo",
        target_worker="demo_worker",
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        requested_active_app=env_bad_app.active_app,
        logger=logger,
    )

    env_builtin = _dummy_worker_env(tmp_path, app_name="flight_telemetry_project")
    builtin_root = tmp_path / "apps" / "builtin"
    candidate_app = builtin_root / "flight_telemetry_project"
    (candidate_app / "src" / "flight_worker").mkdir(parents=True, exist_ok=True)
    (candidate_app / "src" / "flight_worker" / "flight_worker.py").write_text(
        "class FlightWorker:\n    pass\n",
        encoding="utf-8",
    )
    original_resolve = worker_runtime_support.Path.resolve

    def _resolve_with_oserror(self, *args, **kwargs):
        if self == candidate_app:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(worker_runtime_support.Path, "resolve", _resolve_with_oserror, raising=False)
    worker_runtime_support._resolve_builtin_worker_paths(
        env_builtin,
        target="flight",
        target_worker="flight_worker",
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        requested_active_app=env_builtin.active_app,
        logger=logger,
    )
    assert env_builtin.active_app == candidate_app

    env_repo_link = _dummy_worker_env(tmp_path)
    env_repo_link._ensure_repository_app_link = lambda: True
    refresh_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        worker_runtime_support,
        "_refresh_worker_paths",
        lambda env_obj, *, target, target_worker: refresh_calls.append((target, target_worker)),
    )
    worker_runtime_support._copy_missing_worker_sources(
        env_repo_link,
        target_worker="demo_worker",
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        logger=logger,
        copytree_fn=lambda *_args, **_kwargs: None,
    )
    assert refresh_calls == [("demo", "demo_worker")]

    monkeypatch.setattr(worker_runtime_support, "_refresh_worker_paths", worker_runtime_support._refresh_worker_paths)
    env_packaged = _dummy_worker_env(tmp_path)
    packaged_app = env_packaged.agilab_pck / "apps" / "demo_project"
    (packaged_app / "src" / "demo_worker").mkdir(parents=True, exist_ok=True)
    (packaged_app / "src" / "demo_worker" / "demo_worker.py").write_text("pass\n", encoding="utf-8")

    def _resolve_packaged_oserror(self, *args, **kwargs):
        if self in {packaged_app, env_packaged.active_app}:
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(worker_runtime_support.Path, "resolve", _resolve_packaged_oserror, raising=False)
    worker_runtime_support._copy_missing_worker_sources(
        env_packaged,
        target_worker="demo_worker",
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        logger=logger,
        copytree_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )
    assert logger.warning.called

    monkeypatch.setattr(worker_runtime_support.Path, "resolve", original_resolve, raising=False)
    env_project_worker = _dummy_worker_env(tmp_path, app_name="demo_worker")
    env_project_worker.target = "demo"
    project_worker_dir = tmp_path / "apps" / "demo_project" / "src" / "demo_worker"
    project_worker_dir.mkdir(parents=True, exist_ok=True)
    copy_calls: list[tuple[Path, Path]] = []
    refresh_calls.clear()
    monkeypatch.setattr(
        worker_runtime_support,
        "_refresh_worker_paths",
        lambda env_obj, *, target, target_worker: refresh_calls.append((target, target_worker)),
    )
    worker_runtime_support._copy_missing_worker_sources(
        env_project_worker,
        target_worker="demo_worker",
        apps_path=tmp_path / "apps",
        apps_root=tmp_path / "apps",
        logger=logger,
        copytree_fn=lambda src, dst, dirs_exist_ok=True: copy_calls.append((src, dst)),
    )
    assert copy_calls == [(project_worker_dir, env_project_worker.active_app / "src" / "demo_worker")]
    assert refresh_calls == [("demo", "demo_worker")]


def test_share_runtime_support_probe_failures_cover_remaining_branches(monkeypatch):
    assert share_runtime_support.is_valid_ip("999.0.0.1") is False
    monkeypatch.setattr(
        share_runtime_support.sysconfig,
        "get_config_var",
        lambda _name: (_ for _ in ()).throw(OSError("bad config")),
    )
    monkeypatch.delattr(share_runtime_support.sys, "_is_gil_enabled", raising=False)
    assert share_runtime_support.python_supports_free_threading() is False


def test_agi_env_small_helpers_cover_remaining_branches(tmp_path: Path, monkeypatch):

    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("[cluster]\nother = true\n", encoding="utf-8")
    assert share_mount_support._read_cluster_setting(settings_path) is None
    usable_dir = tmp_path / "cluster"
    usable_dir.mkdir()
    assert share_mount_support.is_mounted(str(usable_dir), home_path=tmp_path) is True

    class _State(dict):
        def __getattr__(self, name):
            return self[name]

        def __setattr__(self, name, value):
            self[name] = value

    state = _State({"env": SimpleNamespace(change_app=lambda _path: None, apps_path=tmp_path, target="demo", active_app=tmp_path / "demo", AGILAB_EXPORT_ABS=tmp_path / "export")})
    pagelib_project_support.on_project_change(
        "demo_project",
        session_state=state,
        store_last_active_app_fn=lambda _path: (_ for _ in ()).throw(OSError("store failed")),
        clear_project_session_state_fn=lambda _session: None,
        reset_project_sections_fn=lambda _session: None,
        error_fn=lambda _message: (_ for _ in ()).throw(AssertionError("should not fail")),
    )
    assert state["project_changed"] is True

    env_store = {"KEEP_ME": "old", "DROP_ME": "legacy"}
    output = pagelib_execution_support.run_lab(
        [0, "desc", "print('ok')"],
        tmp_path / "snippet.py",
        str(tmp_path / "snippet.py"),
        env_overrides={"KEEP_ME": "new", "DROP_ME": None},
        warning_fn=lambda _message: None,
        os_module=SimpleNamespace(environ=env_store),
        sys_module=SimpleNamespace(stdout=None, stderr=None),
        runpy_module=SimpleNamespace(run_path=lambda _path: (_ for _ in ()).throw(RuntimeError("boom"))),
    )
    assert "Error: boom" in output
    assert env_store["KEEP_ME"] == "old"
    assert env_store["DROP_ME"] == "legacy"

    context = package_layout_support.resolve_agilab_package_context(
        repo_agilab_dir=tmp_path / "repo",
        find_spec_fn=lambda _name: None,
        path_cls=Path,
    )
    assert context.package_dir == (tmp_path / "repo").resolve()

    def _missing_spec(_name):
        return None

    installed_root = tmp_path / "installed"
    env_pkg = installed_root / "agi_env"
    node_pkg = installed_root / "agi_node"
    env_pkg.mkdir(parents=True, exist_ok=True)
    node_pkg.mkdir(parents=True, exist_ok=True)

    def _resolve_package_dir(spec_name, **_kwargs):
        mapping = {
            "agi_env": env_pkg,
            "agi_node": node_pkg,
        }
        if spec_name not in mapping:
            raise ModuleNotFoundError(spec_name)
        return mapping[spec_name]

    layout = package_layout_support.resolve_package_layout(
        is_source_env=False,
        repo_agilab_dir=tmp_path / "repo",
        installed_package_dir=installed_root,
        resolve_package_dir_fn=_resolve_package_dir,
        find_spec_fn=_missing_spec,
        path_cls=Path,
    )
    assert layout.agilab_pck == installed_root

    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "dir_only").mkdir()
    project_clone_support.clone_directory(
        source_root,
        tmp_path / "dest",
        {},
        SimpleNamespace(match_file=lambda _path: False),
        source_root,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True),
        content_renamer_cls=lambda text, rename_map: text,
        replace_content_fn=lambda text, rename_map: text,
    )

    session_state = _State()
    pagelib_selection_support.on_df_change(
        Path("demo"),
        "legacy",
        None,
        None,
        session_state=session_state,
        resolve_selected_df_path_fn=lambda *_args, **_kwargs: None,
        load_last_stage_fn=lambda *_args, **_kwargs: None,
        logger=mock.Mock(),
    )
    assert "legacydf_file" not in session_state
    assert session_state["page_broken"] is True

    assert pagelib_preview_support.resolve_preview_nrows(None, None) is None
    assert pagelib_data_support._normalize_extension("") == ""

    fake_keyring = object()
    monkeypatch.setitem(__import__("sys").modules, "keyring", fake_keyring)
    assert credential_store_support._load_keyring_module() is fake_keyring

    assert agi_logger._is_same_log_record_file(
        "/tmp/frame.py",
        "/tmp/record.py",
        samefile_fn=lambda *_args: (_ for _ in ()).throw(OSError("samefile failed")),
        basename_fn=lambda path: Path(path).name,
    ) is False
