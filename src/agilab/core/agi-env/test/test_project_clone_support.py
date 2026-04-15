from pathlib import Path
from unittest import mock

import pytest

from agi_env.project_clone_support import (
    clone_project,
    copy_existing_projects,
    create_rename_map,
)


def test_create_rename_map_covers_core_aliases():
    mapping = create_rename_map(Path("flight_project"), Path("demo_project"))
    assert mapping["flight_project"] == "demo_project"
    assert mapping["src/flight_worker"] == "src/demo_worker"
    assert mapping["FlightWorker"] == "DemoWorker"
    assert mapping["flight_args"] == "demo_args"


def test_clone_project_uses_template_source_and_updates_projects(tmp_path: Path):
    apps_path = tmp_path / "apps"
    template_src = apps_path / "templates" / "alpha_project"
    template_src.mkdir(parents=True)
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    projects: list[Path] = []
    logger = mock.Mock()
    calls: dict[str, object] = {}

    def _clone_directory(source_dir, dest_dir, rename_map, _spec, source_root):
        calls["source"] = source_dir
        calls["dest"] = dest_dir
        calls["rename_map"] = rename_map
        calls["source_root"] = source_root

    def _cleanup(root, rename_map):
        calls["cleanup"] = (root, rename_map)

    clone_project(
        Path("alpha"),
        Path("beta"),
        apps_path=apps_path,
        home_abs=home_abs,
        projects=projects,
        logger=logger,
        create_rename_map_fn=create_rename_map,
        clone_directory_fn=_clone_directory,
        cleanup_rename_fn=_cleanup,
    )

    assert calls["source"] == template_src
    assert calls["dest"] == apps_path / "beta_project"
    assert calls["source_root"] == template_src
    assert projects and projects[0] == Path("beta_project")


def test_copy_existing_projects_merges_nested_projects(tmp_path: Path):
    src_apps = tmp_path / "src"
    dst_apps = tmp_path / "dst"
    nested = src_apps / "group" / "alpha_project"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("print('ok')\n", encoding="utf-8")
    logger = mock.Mock()

    copy_existing_projects(
        src_apps,
        dst_apps,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        logger=logger,
    )

    assert (dst_apps / "group" / "alpha_project" / "main.py").exists()


def test_copy_existing_projects_handles_operational_failures_and_propagates_runtime_bug(tmp_path: Path, monkeypatch):
    src_apps = tmp_path / "src"
    dst_apps = tmp_path / "dst"
    nested = src_apps / "group" / "alpha_project"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("print('ok')\n", encoding="utf-8")
    logger = mock.Mock()
    original_resolve = Path.resolve
    resolve_calls = {"count": 0}

    def _oserror_resolve(self, *args, **kwargs):
        if self in {src_apps, dst_apps} and resolve_calls["count"] < 1:
            resolve_calls["count"] += 1
            raise OSError("resolve failed")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _oserror_resolve, raising=False)
    monkeypatch.setattr(
        "agi_env.project_clone_support.shutil.copytree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )

    copy_existing_projects(
        src_apps,
        dst_apps,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        logger=logger,
    )
    assert logger.error.called

    def _runtime_resolve(self, *args, **kwargs):
        if self in {src_apps, dst_apps}:
            raise RuntimeError("resolve bug")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _runtime_resolve, raising=False)
    with pytest.raises(RuntimeError, match="resolve bug"):
        copy_existing_projects(
            src_apps,
            dst_apps,
            ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
            logger=logger,
        )


def test_copy_existing_projects_propagates_unexpected_copytree_bug(tmp_path: Path, monkeypatch):
    src_apps = tmp_path / "src"
    dst_apps = tmp_path / "dst"
    nested = src_apps / "group" / "alpha_project"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("print('ok')\n", encoding="utf-8")
    logger = mock.Mock()

    monkeypatch.setattr(
        "agi_env.project_clone_support.shutil.copytree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("copy bug")),
    )

    with pytest.raises(RuntimeError, match="copy bug"):
        copy_existing_projects(
            src_apps,
            dst_apps,
            ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
            logger=logger,
        )


def test_clone_project_handles_operational_failures_and_propagates_runtime_bug(tmp_path: Path, monkeypatch):
    apps_path = tmp_path / "apps"
    source_root = apps_path / "alpha_project"
    source_root.mkdir(parents=True)
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    logger = mock.Mock()
    projects: list[Path] = []
    original_mkdir = Path.mkdir

    def _oserror_mkdir(self, *args, **kwargs):
        if self == apps_path / "beta_project":
            raise OSError("mkdir failed")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _oserror_mkdir, raising=False)
    clone_project(
        Path("alpha_project"),
        Path("beta_project"),
        apps_path=apps_path,
        home_abs=home_abs,
        projects=projects,
        logger=logger,
        create_rename_map_fn=create_rename_map,
        clone_directory_fn=lambda *_args, **_kwargs: None,
        cleanup_rename_fn=lambda *_args, **_kwargs: None,
    )
    assert logger.error.called

    def _runtime_mkdir(self, *args, **kwargs):
        if self == apps_path / "beta_project":
            raise RuntimeError("mkdir bug")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", _runtime_mkdir, raising=False)
    with pytest.raises(RuntimeError, match="mkdir bug"):
        clone_project(
            Path("alpha_project"),
            Path("beta_project"),
            apps_path=apps_path,
            home_abs=home_abs,
            projects=[],
            logger=logger,
            create_rename_map_fn=create_rename_map,
            clone_directory_fn=lambda *_args, **_kwargs: None,
            cleanup_rename_fn=lambda *_args, **_kwargs: None,
        )


def test_clone_project_data_copy_handles_operational_failure_and_propagates_runtime_bug(tmp_path: Path):
    apps_path = tmp_path / "apps"
    source_root = apps_path / "alpha_project"
    source_root.mkdir(parents=True)
    home_abs = tmp_path / "home"
    (home_abs / "data" / "alpha").mkdir(parents=True)
    logger = mock.Mock()

    clone_project(
        Path("alpha_project"),
        Path("beta_project"),
        apps_path=apps_path,
        home_abs=home_abs,
        projects=[],
        logger=logger,
        create_rename_map_fn=create_rename_map,
        clone_directory_fn=lambda *_args, **_kwargs: None,
        cleanup_rename_fn=lambda *_args, **_kwargs: None,
        copytree_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy failed")),
    )
    assert logger.info.called

    with pytest.raises(RuntimeError, match="copy bug"):
        clone_project(
            Path("alpha_project"),
            Path("gamma_project"),
            apps_path=apps_path,
            home_abs=home_abs,
            projects=[],
            logger=logger,
            create_rename_map_fn=create_rename_map,
            clone_directory_fn=lambda *_args, **_kwargs: None,
            cleanup_rename_fn=lambda *_args, **_kwargs: None,
            copytree_fn=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("copy bug")),
        )
