from io import UnsupportedOperation
from pathlib import Path
from unittest import mock

import pytest
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern

from agi_env.project_clone_support import (
    cleanup_rename,
    clone_directory,
    clone_project,
    copy_existing_projects,
    create_rename_map,
)


def test_create_rename_map_covers_core_aliases():
    mapping = create_rename_map(Path("flight_telemetry_project"), Path("demo_project"))
    assert mapping["flight_telemetry_project"] == "demo_project"
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


def test_copy_existing_projects_uses_sorted_project_order_when_rglob_varies(tmp_path: Path, monkeypatch):
    src_apps = tmp_path / "src"
    dst_apps = tmp_path / "dst"
    alpha = src_apps / "alpha_project"
    zeta = src_apps / "nested" / "zeta_project"
    alpha.mkdir(parents=True)
    zeta.mkdir(parents=True)
    copy_order: list[Path] = []
    logger = mock.Mock()

    real_rglob = Path.rglob

    def _fake_rglob(self: Path, pattern: str):
        if self == src_apps and pattern == "*_project":
            return iter([zeta, alpha])
        return real_rglob(self, pattern)

    monkeypatch.setattr(Path, "rglob", _fake_rglob)
    monkeypatch.setattr(
        "agi_env.project_clone_support.shutil.copytree",
        lambda src, dst, **kwargs: copy_order.append(Path(src)),
    )

    copy_existing_projects(
        src_apps,
        dst_apps,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        logger=logger,
    )

    assert copy_order == [alpha, zeta]


def test_copy_existing_projects_noops_for_same_tree_and_skips_non_directory_candidates(tmp_path: Path):
    src_apps = tmp_path / "src"
    src_apps.mkdir()
    (src_apps / "ghost_project").write_text("not a directory", encoding="utf-8")
    logger = mock.Mock()

    copy_existing_projects(
        src_apps,
        src_apps,
        ensure_dir_fn=lambda path: Path(path),
        logger=logger,
    )
    assert not logger.info.called

    dst_apps = tmp_path / "dst"
    copy_existing_projects(
        src_apps,
        dst_apps,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        logger=logger,
    )
    assert not (dst_apps / "ghost_project").exists()


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


def test_copy_existing_projects_swallow_unsupported_operation_from_resolve(tmp_path: Path, monkeypatch):
    src_apps = tmp_path / "src"
    dst_apps = tmp_path / "dst"
    nested = src_apps / "group" / "alpha_project"
    nested.mkdir(parents=True)
    (nested / "main.py").write_text("print('ok')\n", encoding="utf-8")
    logger = mock.Mock()
    original_resolve = Path.resolve

    def _unsupported_resolve(self, *args, **kwargs):
        if self in {src_apps, dst_apps}:
            raise UnsupportedOperation("resolve unsupported on host")
        return original_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", _unsupported_resolve, raising=False)

    copy_existing_projects(
        src_apps,
        dst_apps,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        logger=logger,
    )

    assert (dst_apps / "group" / "alpha_project" / "main.py").exists()


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


def test_clone_project_ignores_unreadable_gitignore_and_continues(tmp_path: Path, monkeypatch):
    apps_path = tmp_path / "apps"
    source_root = apps_path / "alpha_project"
    source_root.mkdir(parents=True)
    gitignore = source_root / ".gitignore"
    gitignore.write_text("ignored/\n", encoding="utf-8")
    home_abs = tmp_path / "home"
    home_abs.mkdir()
    logger = mock.Mock()
    calls: list[tuple[Path, Path]] = []
    original_read_text = Path.read_text

    def _oserror_read_text(self, *args, **kwargs):
        if self == gitignore:
            raise OSError("gitignore failed")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _oserror_read_text, raising=False)

    clone_project(
        Path("alpha_project"),
        Path("beta_project"),
        apps_path=apps_path,
        home_abs=home_abs,
        projects=[],
        logger=logger,
        create_rename_map_fn=create_rename_map,
        clone_directory_fn=lambda source_dir, dest_dir, *_args: calls.append((source_dir, dest_dir)),
        cleanup_rename_fn=lambda *_args, **_kwargs: None,
    )

    assert calls == [(source_root, apps_path / "beta_project")]
    assert logger.debug.called


def test_clone_directory_and_cleanup_rename_cover_symlink_archive_syntax_and_text_paths(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    dest_root = tmp_path / "dest"
    rename_map = {"flight": "demo", "flight_telemetry_project": "demo_project"}
    spec = PathSpec.from_lines(GitWildMatchPattern, [])

    link_target = source_root / "target.txt"
    link_target.write_text("flight", encoding="utf-8")
    link_path = source_root / "link.txt"
    link_path.symlink_to(link_target)
    (source_root / ".venv").mkdir()
    archive = source_root / "flight.zip"
    archive.write_bytes(b"zip")
    invalid_py = source_root / "flight.py"
    invalid_py.write_text("def broken(:\n", encoding="utf-8")
    text_file = source_root / "flight.txt"
    text_file.write_text("flight project", encoding="utf-8")

    monkeypatch.setattr(
        "agi_env.project_clone_support.os.readlink",
        lambda path: (_ for _ in ()).throw(OSError("readlink failed")) if Path(path) == link_path else str(link_target),
    )

    clone_directory(
        source_root,
        dest_root,
        rename_map,
        spec,
        source_root,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        content_renamer_cls=lambda _rename_map: type("NoOpRenamer", (), {"visit": lambda self, tree: tree})(),
        replace_content_fn=lambda text, mapping: text.replace("flight", "demo"),
    )

    assert (dest_root / "link.txt").is_symlink()
    assert (dest_root / ".venv").is_symlink()
    assert (dest_root / "demo.zip").read_bytes() == b"zip"
    assert "def broken" in (dest_root / "demo.py").read_text(encoding="utf-8")
    assert (dest_root / "demo.txt").read_text(encoding="utf-8") == "demo project"

    cleanup_root = tmp_path / "cleanup"
    cleanup_root.mkdir()
    (cleanup_root / "flight").write_text("flight", encoding="utf-8")
    (cleanup_root / "flight_telemetry_project").write_text("flight project", encoding="utf-8")
    (cleanup_root / "flight.txt").write_text("flight text", encoding="utf-8")

    cleanup_rename(
        cleanup_root,
        rename_map,
        replace_content_fn=lambda text, mapping: text.replace("flight", "demo"),
    )

    assert (cleanup_root / "demo").exists()
    assert (cleanup_root / "demo_project").exists()
    assert (cleanup_root / "demo.txt").read_text(encoding="utf-8") == "demo text"


def test_clone_directory_skips_entries_that_are_neither_files_nor_directories(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    odd_entry = source_root / "odd.bin"
    odd_entry.write_text("payload", encoding="utf-8")
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    spec = PathSpec.from_lines(GitWildMatchPattern, [])

    original_is_file = Path.is_file
    original_is_dir = Path.is_dir

    def _patched_is_file(self):
        if self == odd_entry:
            return False
        return original_is_file(self)

    def _patched_is_dir(self):
        if self == odd_entry:
            return False
        return original_is_dir(self)

    monkeypatch.setattr(Path, "is_file", _patched_is_file, raising=False)
    monkeypatch.setattr(Path, "is_dir", _patched_is_dir, raising=False)

    clone_directory(
        source_root,
        dest_root,
        {},
        spec,
        source_root,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        content_renamer_cls=lambda _rename_map: type("NoOpRenamer", (), {"visit": lambda self, tree: tree})(),
        replace_content_fn=lambda text, _mapping: text,
    )

    assert not (dest_root / "odd.bin").exists()
