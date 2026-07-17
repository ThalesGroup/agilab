from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import tomllib

import pytest

import agi_env.app_settings_support as app_settings_module
import agi_env.runtime.atomic_write_support as atomic_write_module


def test_app_settings_lock_times_out_instead_of_freezing_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "app_settings.toml"
    monkeypatch.setattr(app_settings_module, "_APP_SETTINGS_LOCK_TIMEOUT_SECONDS", 0.01)

    with app_settings_module.app_settings_file_lock(settings):
        with pytest.raises(TimeoutError, match="Another session"):
            with app_settings_module.app_settings_file_lock(settings):
                raise AssertionError("nested lock unexpectedly acquired")


def test_read_app_settings_retries_transient_windows_sharing_violation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text('[args]\nstatus = "ready"\n', encoding="utf-8")
    real_read_text = Path.read_text
    attempts = 0

    def _transient_read_text(path: Path, *args, **kwargs) -> str:
        nonlocal attempts
        if path == settings:
            attempts += 1
            if attempts == 1:
                raise PermissionError("sharing violation")
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(atomic_write_module, "_is_windows", lambda: True)
    monkeypatch.setattr(atomic_write_module.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(Path, "read_text", _transient_read_text)

    assert app_settings_module.read_app_settings(settings) == {
        "args": {"status": "ready"}
    }
    assert attempts == 2


def test_read_app_settings_surfaces_parse_errors_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text("[args\n", encoding="utf-8")
    real_read_text = Path.read_text
    attempts = 0

    def _counted_read_text(path: Path, *args, **kwargs) -> str:
        nonlocal attempts
        if path == settings:
            attempts += 1
        return real_read_text(path, *args, **kwargs)

    monkeypatch.setattr(atomic_write_module, "_is_windows", lambda: True)
    monkeypatch.setattr(Path, "read_text", _counted_read_text)

    with pytest.raises(tomllib.TOMLDecodeError):
        app_settings_module.read_app_settings(settings)

    assert attempts == 1


def test_prepare_app_settings_for_write_sanitizes_and_stamps_metadata(tmp_path: Path):
    payload = {
        "args": {
            "data_in": tmp_path / "data",
            "unused": None,
            "items": (tmp_path / "a", None, "b"),
        }
    }

    prepared = app_settings_module.prepare_app_settings_for_write(payload)

    assert prepared == {
        "__meta__": {"schema": "agilab.app_settings.v1", "version": 1},
        "args": {"data_in": str(tmp_path / "data"), "items": [str(tmp_path / "a"), "b"]},
    }
    assert payload["args"]["unused"] is None


def test_prepare_app_settings_for_write_preserves_supported_metadata():
    payload = {"__meta__": {"schema": "custom.schema", "version": "1", "owner": "test"}}

    prepared = app_settings_module.prepare_app_settings_for_write(payload)

    assert prepared["__meta__"] == {"schema": "custom.schema", "version": "1", "owner": "test"}


def test_prepare_app_settings_for_write_normalizes_legacy_run_args_key():
    payload = {
        "args": {
            "data_in": "network_sim/pipeline",
            "data_out": "sb3_trainer/pipeline",
            "args": [{"name": "train", "args": {"seed": 42}}],
        }
    }

    prepared = app_settings_module.prepare_app_settings_for_write(payload)

    assert "args" not in prepared["args"]
    assert prepared["args"]["stages"] == [{"name": "train", "args": {"seed": 42}}]
    assert prepared["args"]["data_in"] == "network_sim/pipeline"
    assert prepared["args"]["data_out"] == "sb3_trainer/pipeline"


def test_prepare_app_settings_for_write_rejects_ambiguous_run_stage_keys():
    with pytest.raises(ValueError, match="cannot contain both legacy 'args.args' and current 'args.stages'"):
        app_settings_module.prepare_app_settings_for_write(
            {
                "args": {
                    "args": [{"name": "legacy"}],
                    "stages": [{"name": "current"}],
                }
            }
        )


def test_prepare_app_settings_for_write_rejects_invalid_metadata():
    with pytest.raises(ValueError, match="__meta__ must be a TOML table"):
        app_settings_module.prepare_app_settings_for_write({"__meta__": "bad"})

    with pytest.raises(ValueError, match="Unsupported app_settings.toml schema version 'bad'"):
        app_settings_module.prepare_app_settings_for_write({"__meta__": {"version": "bad"}})

    with pytest.raises(ValueError, match="Unsupported app_settings.toml schema version 2"):
        app_settings_module.prepare_app_settings_for_write(
            {"__meta__": {"schema": "agilab.app_settings.v2", "version": 2}}
        )


def test_update_app_settings_serializes_disjoint_thread_updates(tmp_path: Path) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text('[unrelated]\nowner = "preserved"\n', encoding="utf-8")
    first_entered = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    errors: list[BaseException] = []

    def _write_pages() -> None:
        try:
            def _update(payload):
                payload["pages"] = {"view_module": ["view_maps"]}
                first_entered.set()
                assert release_first.wait(timeout=5)
                return True

            app_settings_module.update_app_settings(settings, _update)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    def _write_cluster() -> None:
        try:
            second_started.set()

            def _update(payload):
                payload["cluster"] = {"cluster_enabled": False}
                return True

            app_settings_module.update_app_settings(settings, _update)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    pages_thread = threading.Thread(target=_write_pages)
    cluster_thread = threading.Thread(target=_write_cluster)
    pages_thread.start()
    assert first_entered.wait(timeout=5)
    cluster_thread.start()
    assert second_started.wait(timeout=5)
    time.sleep(0.05)
    release_first.set()
    pages_thread.join(timeout=5)
    cluster_thread.join(timeout=5)

    assert not pages_thread.is_alive()
    assert not cluster_thread.is_alive()
    assert errors == []
    payload = tomllib.loads(settings.read_text(encoding="utf-8"))
    assert payload["pages"] == {"view_module": ["view_maps"]}
    assert payload["cluster"] == {"cluster_enabled": False}
    assert payload["unrelated"] == {"owner": "preserved"}


def test_update_app_settings_owned_merges_stale_cross_writer_leaves(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text(
        "[cluster]\nscheduler = \"old\"\n\n"
        "[cluster.service_health]\nallow_idle = false\n",
        encoding="utf-8",
    )
    service_snapshot = {
        "cluster": {
            "scheduler": "old",
            "service_health": {"allow_idle": True},
        }
    }
    cluster_snapshot = {
        "cluster": {
            "scheduler": "new",
            "service_health": {"allow_idle": False},
        }
    }

    app_settings_module.update_app_settings_owned(
        settings,
        service_snapshot,
        owned_paths=(("cluster", "service_health"),),
    )
    app_settings_module.update_app_settings_owned(
        settings,
        cluster_snapshot,
        owned_paths=(("cluster", "scheduler"),),
    )

    payload = tomllib.loads(settings.read_text(encoding="utf-8"))
    assert payload["cluster"] == {
        "scheduler": "new",
        "service_health": {"allow_idle": True},
    }


def test_update_app_settings_owned_defaults_only_fill_missing_latest_leaves(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "app_settings.toml"
    app_settings_module.update_app_settings_owned(
        settings,
        {"cluster": {"scheduler": "remote"}},
        owned_paths=(),
        default_paths=(("cluster", "scheduler"),),
    )

    # A second pre-seeded session may initialize other missing leaves, but its
    # stale scheduler default must not replace the first session's value.
    latest, changed = app_settings_module.update_app_settings_owned(
        settings,
        {
            "cluster": {
                "scheduler": "stale",
                "cluster_enabled": True,
            }
        },
        owned_paths=(),
        default_paths=(
            ("cluster", "scheduler"),
            ("cluster", "cluster_enabled"),
        ),
    )

    assert changed is True
    assert latest["cluster"] == {
        "scheduler": "remote",
        "cluster_enabled": True,
    }
    assert tomllib.loads(settings.read_text(encoding="utf-8"))["cluster"] == {
        "scheduler": "remote",
        "cluster_enabled": True,
    }


def test_update_app_settings_owned_serializes_disjoint_processes(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "app_settings.toml"
    settings.write_text('[unrelated]\nowner = "preserved"\n', encoding="utf-8")
    start_marker = tmp_path / "start"
    worker_code = (
        "import sys, time\n"
        "from pathlib import Path\n"
        "from agi_env.app_settings_support import update_app_settings_owned\n"
        "settings, section, value, marker = sys.argv[1:]\n"
        "while not Path(marker).exists():\n"
        "    time.sleep(0.01)\n"
        "update_app_settings_owned(settings, {section: {'value': value}}, "
        "owned_paths=((section,),))\n"
    )
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-c",
                worker_code,
                str(settings),
                section,
                value,
                str(start_marker),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for section, value in (("pages", "maps"), ("cluster", "local"))
    ]
    start_marker.touch()
    results = [process.communicate(timeout=15) for process in processes]

    assert [process.returncode for process in processes] == [0, 0], results
    payload = tomllib.loads(settings.read_text(encoding="utf-8"))
    assert payload["pages"] == {"value": "maps"}
    assert payload["cluster"] == {"value": "local"}
    assert payload["unrelated"] == {"owner": "preserved"}


def test_update_app_settings_writer_failure_preserves_prior_valid_toml(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "app_settings.toml"
    original = '[cluster]\ncluster_enabled = true\n'
    settings.write_text(original, encoding="utf-8")

    def _update(payload):
        payload["pages"] = {"view_module": ["view_maps"]}
        return True

    def _broken_writer(_payload, stream):
        stream.write(b"partial")
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        app_settings_module.update_app_settings(
            settings,
            _update,
            dump_fn=_broken_writer,
        )

    assert settings.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".app_settings.toml.*.tmp")) == []


def test_update_app_settings_publication_failure_preserves_prior_valid_toml(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "app_settings.toml"
    original = '[cluster]\ncluster_enabled = true\n'
    settings.write_text(original, encoding="utf-8")

    def _update(payload):
        payload["pages"] = {"view_module": ["view_maps"]}
        return True

    def _fail_replace(_source, _target):
        raise OSError("publication failed")

    monkeypatch.setattr(atomic_write_module.os, "replace", _fail_replace)
    with pytest.raises(OSError, match="publication failed"):
        app_settings_module.update_app_settings(settings, _update)

    assert settings.read_text(encoding="utf-8") == original
    assert list(tmp_path.glob(".app_settings.toml.*.tmp")) == []


def test_update_app_settings_fsyncs_parent_after_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "nested" / "app_settings.toml"
    synced: list[Path] = []
    monkeypatch.setattr(
        app_settings_module,
        "_fsync_directory",
        lambda path: synced.append(path),
    )

    def _update(payload):
        payload["pages"] = {"view_module": ["view_maps"]}
        return True

    app_settings_module.update_app_settings(settings, _update)

    assert synced == [settings.parent]
    assert tomllib.loads(settings.read_text(encoding="utf-8"))["pages"] == {
        "view_module": ["view_maps"]
    }


def test_app_settings_aliases_and_candidate_paths(tmp_path: Path):
    assert app_settings_module.app_settings_aliases("demo_project") == {"demo_project", "demo_worker"}
    assert app_settings_module.app_settings_aliases("demo_worker") == {"demo_worker", "demo_project"}
    assert app_settings_module.app_settings_aliases("demo_project_worker") == {
        "demo_project",
        "demo_project_worker",
    }
    assert app_settings_module.app_settings_aliases("demo") == {"demo"}
    assert app_settings_module.app_settings_aliases(None) == set()

    src_dir = tmp_path / "demo_project" / "src"
    src_dir.mkdir(parents=True)
    src_settings = src_dir / "app_settings.toml"
    src_settings.write_text("[cluster]\ncluster_enabled = false\n", encoding="utf-8")

    assert app_settings_module.candidate_app_settings_path(src_dir) == src_settings
    assert app_settings_module.candidate_app_settings_path(src_dir.parent) == src_settings
    assert app_settings_module.candidate_app_settings_path(object()) is None
    assert app_settings_module.candidate_app_settings_path(tmp_path / "missing") is None


def test_app_settings_contract_error_rejects_future_and_invalid_metadata() -> None:
    assert app_settings_module.app_settings_contract_error({"__meta__": {"version": 999}}).startswith(
        "Unsupported app_settings.toml schema version 999"
    )
    assert app_settings_module.app_settings_contract_error({"__meta__": "bad"}) == (
        "app_settings.toml __meta__ must be a TOML table."
    )


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


def test_resolve_user_app_settings_serializes_atomic_first_creation(
    tmp_path: Path,
) -> None:
    resources_path = tmp_path / "resources"
    source_a = tmp_path / "source-a.toml"
    source_b = tmp_path / "source-b.toml"
    source_a.write_text('[owner]\nname = "alpha"\n', encoding="utf-8")
    source_b.write_text('[owner]\nname = "beta"\n', encoding="utf-8")
    copy_started = threading.Event()
    release_copy = threading.Event()
    errors: list[BaseException] = []

    def _blocking_copy(source: Path, target: Path) -> object:
        copy_started.set()
        assert release_copy.wait(timeout=5)
        return shutil.copy2(source, target)

    def _resolve(source: Path, copy_file=shutil.copy2) -> None:
        try:
            app_settings_module.resolve_user_app_settings_file(
                target_app="demo_project",
                resources_path=resources_path,
                find_source_file=lambda _app=None: source,
                copy_file=copy_file,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(target=_resolve, args=(source_a, _blocking_copy))
    second = threading.Thread(target=_resolve, args=(source_b,))
    first.start()
    assert copy_started.wait(timeout=5)
    second.start()
    workspace_file = (
        resources_path / "apps" / "demo_project" / "app_settings.toml"
    )
    assert not workspace_file.exists()
    release_copy.set()
    first.join(timeout=5)
    second.join(timeout=5)

    assert errors == []
    assert workspace_file.read_text(encoding="utf-8") == source_a.read_text(
        encoding="utf-8"
    )


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


def test_candidate_and_user_app_settings_cover_existing_workspace_and_probe_oserror(tmp_path: Path, monkeypatch):
    src_dir = tmp_path / "demo_project" / "src"
    src_dir.mkdir(parents=True)
    src_settings = src_dir / "app_settings.toml"
    src_settings.write_text("[cluster]\ncluster_enabled = true\n", encoding="utf-8")

    original_is_dir = Path.is_dir

    def _oserror_is_dir(self):
        if self == src_dir:
            raise OSError("probe failed")
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_dir", _oserror_is_dir, raising=False)
    assert app_settings_module.candidate_app_settings_path(src_dir.parent) == src_settings

    resources_path = tmp_path / ".agilab"
    workspace_file = resources_path / "apps" / "demo_project" / "app_settings.toml"
    workspace_file.parent.mkdir(parents=True)
    workspace_file.write_text("existing", encoding="utf-8")

    resolved = app_settings_module.resolve_user_app_settings_file(
        target_app="demo_project",
        resources_path=resources_path,
        find_source_file=lambda _app_name=None: src_settings,
    )
    assert resolved == workspace_file
    assert resolved.read_text(encoding="utf-8") == "existing"


def test_candidate_app_settings_path_returns_none_when_src_dir_probe_oserror(tmp_path: Path, monkeypatch):
    app_dir = tmp_path / "demo_project"
    app_dir.mkdir(parents=True)
    src_dir = app_dir / "src"

    original_is_file = Path.is_file
    original_is_dir = Path.is_dir

    def _patched_is_file(self):
        return original_is_file(self)

    def _patched_is_dir(self):
        if self == src_dir:
            raise OSError("probe failed")
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_file", _patched_is_file, raising=False)
    monkeypatch.setattr(Path, "is_dir", _patched_is_dir, raising=False)

    assert app_settings_module.candidate_app_settings_path(app_dir) is None
