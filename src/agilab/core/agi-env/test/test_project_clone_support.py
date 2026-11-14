from io import UnsupportedOperation
from pathlib import Path
from unittest import mock

import pytest
from pathspec.gitignore import GitIgnoreSpec

from agi_env.content_renamer_support import ContentRenamer
import agi_env.project_clone_support as project_clone_support
from agi_env.project_clone_support import (
    cleanup_rename,
    clone_directory,
    clone_project,
    copy_existing_projects,
    create_rename_map,
)
from agi_env.rename_gitignore_support import replace_text_content


def test_create_rename_map_covers_core_aliases():
    mapping = create_rename_map(Path("flight_telemetry_project"), Path("demo_project"))
    assert mapping["flight_telemetry_project"] == "demo_project"
    assert mapping["src/flight_telemetry_worker"] == "src/demo_worker"
    assert mapping["FlightTelemetryWorker"] == "DemoWorker"
    assert mapping["flight_telemetry_args"] == "demo_args"


def test_create_rename_map_covers_data_io_2026_to_mission_decision():
    mapping = create_rename_map(Path("data_io_2026_project"), Path("mission_decision_project"))

    assert mapping["data_io_2026_project"] == "mission_decision_project"
    assert mapping["src/data_io_2026"] == "src/mission_decision"
    assert mapping["src/data_io_2026_worker"] == "src/mission_decision_worker"
    assert mapping["data_io_2026"] == "mission_decision"
    assert mapping["DataIo2026"] == "MissionDecision"
    assert mapping["DataIo2026Worker"] == "MissionDecisionWorker"
    assert mapping["DataIo2026Args"] == "MissionDecisionArgs"


def test_create_rename_map_uses_concrete_names_for_public_aliases():
    mapping = create_rename_map(
        Path("weather_forecast_legacy_project"),
        Path("weather_demo_project"),
    )

    assert mapping["weather_forecast_legacy"] == "weather_demo"
    assert mapping["WeatherForecastLegacyWorker"] == "WeatherDemoWorker"
    assert "weather_forecast" not in mapping


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


def test_copy_existing_projects_rejects_nested_destination_symlink_escape(
    tmp_path: Path,
):
    src_apps = tmp_path / "src"
    dst_apps = tmp_path / "dst"
    source_project = src_apps / "group" / "alpha_project"
    source_project.mkdir(parents=True)
    (source_project / "main.py").write_text("safe\n", encoding="utf-8")
    dst_apps.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    marker = outside / "important.txt"
    marker.write_text("keep", encoding="utf-8")
    try:
        (dst_apps / "group").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable on this filesystem")

    with pytest.raises(
        project_clone_support.ProjectPathConfinementError,
        match="destination parent must stay within",
    ):
        copy_existing_projects(
            src_apps,
            dst_apps,
            ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True)
            or Path(path),
            logger=mock.Mock(),
        )

    assert marker.read_text(encoding="utf-8") == "keep"
    assert not (outside / "alpha_project").exists()


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


def test_cleanup_rename_refuses_to_overwrite_existing_target(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "old.py").write_text("old", encoding="utf-8")
    (root / "new.py").write_text("new", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        cleanup_rename(
            root,
            {"old": "new"},
            replace_content_fn=lambda text, _rename_map: text,
        )

    assert (root / "old.py").exists()
    assert (root / "new.py").read_text(encoding="utf-8") == "new"


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


def test_copy_existing_projects_fails_closed_when_destination_cannot_resolve(
    tmp_path: Path, monkeypatch
):
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

    with pytest.raises(
        project_clone_support.ProjectPathConfinementError,
        match="Cannot verify project copy destination parent root confinement",
    ):
        copy_existing_projects(
            src_apps,
            dst_apps,
            ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True)
            or Path(path),
            logger=logger,
        )

    assert not (dst_apps / "group" / "alpha_project" / "main.py").exists()


def test_git_lfs_helpers_cover_error_edges(tmp_path: Path, monkeypatch):
    pointer = tmp_path / "dataset.7z"
    pointer.write_text("version https://git-lfs.github.com/spec/v1\n", encoding="utf-8")
    git_root = tmp_path / "repo"
    git_root.mkdir()
    outside = tmp_path / "outside" / "dataset.7z"
    outside.parent.mkdir()
    outside.write_text("payload", encoding="utf-8")

    assert project_clone_support._find_git_root(tmp_path / "not-a-repo") is None

    original_read_bytes = Path.read_bytes

    def _read_bytes(self):
        if self == pointer:
            raise OSError("unreadable")
        return original_read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", _read_bytes)
    assert project_clone_support._is_git_lfs_pointer_file(pointer) is False

    with pytest.raises(RuntimeError, match="outside the git root"):
        project_clone_support._git_lfs_include_arg([outside], git_root)


def test_ensure_git_lfs_payloads_reports_missing_git_root_and_binary(
    tmp_path: Path, monkeypatch
):
    source = tmp_path / "project"
    dataset = source / "src" / "demo_worker" / "dataset.7z"
    dataset.parent.mkdir(parents=True)
    dataset.write_text("version https://git-lfs.github.com/spec/v1\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="no git repository root"):
        project_clone_support._ensure_git_lfs_dataset_payloads(source, mock.Mock())

    (source / ".git").mkdir()

    def _missing_git_lfs(*_args, **_kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(project_clone_support.subprocess, "run", _missing_git_lfs)

    with pytest.raises(RuntimeError, match="git-lfs is not available"):
        project_clone_support._ensure_git_lfs_dataset_payloads(source, mock.Mock())


def test_link_helpers_cover_symlink_and_junction_fallbacks(monkeypatch, tmp_path: Path):
    source = tmp_path / "source"
    source.mkdir()
    dest = tmp_path / "dest"

    monkeypatch.setattr(
        project_clone_support.os,
        "symlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(FileExistsError),
    )
    assert project_clone_support._try_link_directory(source, dest) is True
    assert project_clone_support._try_link_symlink(source, dest) is True

    monkeypatch.setattr(
        project_clone_support.os,
        "symlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no symlink")),
    )
    assert project_clone_support._try_link_directory(source, dest, os_name="posix") is False

    run_calls = []

    def _fake_run(cmd, **kwargs):
        run_calls.append((cmd, kwargs))
        return object()

    monkeypatch.setattr(project_clone_support.subprocess, "run", _fake_run)
    assert project_clone_support._try_link_directory(source, dest, os_name="nt") is True
    assert run_calls[0][0][:3] == ["cmd", "/c", "mklink"]

    monkeypatch.setattr(
        project_clone_support.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            project_clone_support.subprocess.CalledProcessError(1, "mklink")
        ),
    )
    assert project_clone_support._try_link_directory(source, dest, os_name="nt") is False


def test_try_link_symlink_falls_back_to_resolved_directory_or_false(monkeypatch, tmp_path: Path):
    item_dir = tmp_path / "item"
    item_dir.mkdir()
    item_file = tmp_path / "item.txt"
    item_file.write_text("x", encoding="utf-8")
    dest = tmp_path / "dest"
    link_calls = []

    monkeypatch.setattr(
        project_clone_support.os,
        "readlink",
        lambda _item: (_ for _ in ()).throw(OSError("not a symlink")),
    )
    monkeypatch.setattr(
        project_clone_support.os,
        "symlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("no symlink")),
    )
    monkeypatch.setattr(
        project_clone_support,
        "_try_link_directory",
        lambda source, current_dest: link_calls.append((source, current_dest)) or True,
    )

    assert project_clone_support._try_link_symlink(item_dir, dest) is True
    assert link_calls == [(item_dir.resolve(strict=False), dest)]
    assert project_clone_support._try_link_symlink(item_file, dest) is False


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


def test_clone_directory_and_cleanup_rename_cover_symlink_archive_syntax_and_text_paths(
    tmp_path: Path,
):
    source_root = tmp_path / "source"
    source_root.mkdir()
    dest_root = tmp_path / "dest"
    rename_map = {"flight": "demo", "flight_telemetry_project": "demo_project"}
    spec = GitIgnoreSpec.from_lines([])

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
    assert (dest_root / "link.txt").resolve() == (dest_root / "target.txt").resolve()
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


def test_cleanup_rename_never_rewrites_through_symlinks(tmp_path: Path):
    root = tmp_path / "clone"
    root.mkdir()
    outside_file = tmp_path / "outside.md"
    outside_file.write_text("flight secret", encoding="utf-8")
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    nested_outside = outside_dir / "nested.md"
    nested_outside.write_text("flight nested secret", encoding="utf-8")
    try:
        (root / "linked-file.md").symlink_to(outside_file)
        (root / "linked-dir").symlink_to(outside_dir, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this filesystem")
    local = root / "local.md"
    local.write_text("flight local", encoding="utf-8")

    cleanup_rename(
        root,
        {"flight": "demo"},
        replace_content_fn=lambda text, _mapping: text.replace("flight", "demo"),
    )

    assert local.read_text(encoding="utf-8") == "demo local"
    assert outside_file.read_text(encoding="utf-8") == "flight secret"
    assert nested_outside.read_text(encoding="utf-8") == "flight nested secret"


def test_clone_directory_rejects_external_source_symlink(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    secret = tmp_path / "id_rsa"
    secret.write_text("private-key", encoding="utf-8")
    try:
        (source_root / "credentials.txt").symlink_to(secret)
    except OSError:
        pytest.skip("symlinks are unavailable on this filesystem")
    dest_root = tmp_path / "dest"

    with pytest.raises(
        project_clone_support.ProjectPathConfinementError,
        match="project source symlink.*must stay within",
    ):
        clone_directory(
            source_root,
            dest_root,
            {},
            GitIgnoreSpec.from_lines([]),
            source_root,
            ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True)
            or Path(path),
            content_renamer_cls=ContentRenamer,
            replace_content_fn=replace_text_content,
        )

    assert secret.read_text(encoding="utf-8") == "private-key"
    assert not (dest_root / "credentials.txt").exists()


def test_clone_directory_rewrites_valid_python_with_stdlib_ast_unparse(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    dest_root = tmp_path / "dest"
    rename_map = {"flight": "demo", "Flight": "Demo"}
    spec = GitIgnoreSpec.from_lines([])
    (source_root / "flight.py").write_text(
        "class Flight:\n"
        "    def run(self):\n"
        "        flight = 'flight'\n"
        "        return flight\n",
        encoding="utf-8",
    )

    clone_directory(
        source_root,
        dest_root,
        rename_map,
        spec,
        source_root,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        content_renamer_cls=ContentRenamer,
        replace_content_fn=replace_text_content,
    )

    cloned = (dest_root / "demo.py").read_text(encoding="utf-8")
    assert "class Demo" in cloned
    assert "flight" not in cloned
    assert "demo" in cloned


def test_clone_directory_keeps_explicit_venv_symlink_when_gitignored(tmp_path: Path):
    source_root = tmp_path / "source"
    source_root.mkdir()
    dest_root = tmp_path / "dest"
    (source_root / ".venv").mkdir()
    (source_root / "ignored.txt").write_text("ignored", encoding="utf-8")
    spec = GitIgnoreSpec.from_lines([".venv/", "ignored.txt"])

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

    assert (dest_root / ".venv").is_symlink()
    assert not (dest_root / "ignored.txt").exists()


def test_clone_directory_uses_windows_junction_when_venv_symlink_is_denied(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    dest_root = tmp_path / "dest"
    (source_root / ".venv").mkdir()
    spec = GitIgnoreSpec.from_lines([])
    calls: list[list[str]] = []

    monkeypatch.setattr(
        project_clone_support.os,
        "symlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("symlink denied")),
    )

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        (dest_root / ".venv").mkdir(parents=True, exist_ok=True)
        return mock.Mock(returncode=0)

    monkeypatch.setattr(project_clone_support.subprocess, "run", _fake_run)

    clone_directory(
        source_root,
        dest_root,
        {},
        spec,
        source_root,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        content_renamer_cls=lambda _rename_map: type("NoOpRenamer", (), {"visit": lambda self, tree: tree})(),
        replace_content_fn=lambda text, _mapping: text,
        link_directory_fn=lambda source, dest: project_clone_support._try_link_directory(
            source,
            dest,
            os_name="nt",
        ),
    )

    assert calls == [
        ["cmd", "/c", "mklink", "/J", str(dest_root / ".venv"), str(source_root / ".venv")]
    ]
    assert (dest_root / ".venv").exists()


def test_clone_directory_skips_venv_when_windows_linking_is_unavailable(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    dest_root = tmp_path / "dest"
    (source_root / ".venv").mkdir()
    spec = GitIgnoreSpec.from_lines([])

    monkeypatch.setattr(
        project_clone_support.os,
        "symlink",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("symlink denied")),
    )
    monkeypatch.setattr(
        project_clone_support.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("junction denied")),
    )

    clone_directory(
        source_root,
        dest_root,
        {},
        spec,
        source_root,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        content_renamer_cls=lambda _rename_map: type("NoOpRenamer", (), {"visit": lambda self, tree: tree})(),
        replace_content_fn=lambda text, _mapping: text,
        link_directory_fn=lambda source, dest: project_clone_support._try_link_directory(
            source,
            dest,
            os_name="nt",
        ),
    )

    assert not (dest_root / ".venv").exists()
    assert not (dest_root / ".venv").is_symlink()


def test_clone_directory_skips_entries_that_are_neither_files_nor_directories(tmp_path: Path, monkeypatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    odd_entry = source_root / "odd.bin"
    odd_entry.write_text("payload", encoding="utf-8")
    dest_root = tmp_path / "dest"
    dest_root.mkdir()
    spec = GitIgnoreSpec.from_lines([])

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

@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("flight_roundtrip", "flight_roundtrip_01a1d57c"),
        ("flight_01a1d57c", "mission_02b7x"),
        ("flight_01a1d57c", "mission"),
    ],
)
def test_clone_numeric_segments_preserve_dynamically_loaded_references(
    tmp_path, monkeypatch, source, destination,
):
    import importlib
    import sys

    from agi_env.content_renamer_support import ContentRenamer

    source_class = "".join(part.title() for part in source.split("_"))
    destination_class = "".join(part.title() for part in destination.split("_"))
    source_root = tmp_path / (source + "_project")
    destination_root = tmp_path / (destination + "_project")
    manager = source_root / "src" / source
    worker = source_root / "src" / (source + "_worker")
    manager.mkdir(parents=True)
    worker.mkdir(parents=True)
    (manager / "__init__.py").write_text("", encoding="utf-8")
    (worker / "__init__.py").write_text("", encoding="utf-8")
    (manager / (source + "_args.py")).write_text(
        f"class {source_class}Args:\n    value = 7\n"
        f"class {source_class}ArgsTD:\n    pass\n",
        encoding="utf-8",
    )
    (manager / (source + ".py")).write_text(
        f"from .{source}_args import {source_class}Args, {source_class}ArgsTD\n"
        f"class {source_class}:\n    args_type = {source_class}Args\n"
        f"    typed_args = {source_class}ArgsTD\n",
        encoding="utf-8",
    )
    (worker / (source + "_worker.py")).write_text(
        f"from {source}.{source} import {source_class}\n"
        f"class {source_class}Worker:\n    manager_type = {source_class}\n",
        encoding="utf-8",
    )
    (source_root / "pyproject.toml").write_text(
        f'[project]\nname = "{source}_project"\n'
        f'[project.scripts]\nrun = "{source}.{source}:{source_class}"\n',
        encoding="utf-8",
    )
    mapping = create_rename_map(source_root, destination_root)
    for suffix in ("", "Worker", "Args", "ArgsTD"):
        assert mapping[source_class + suffix] == destination_class + suffix

    clone_directory(
        source_root, destination_root, mapping, GitIgnoreSpec.from_lines([]),
        source_root,
        ensure_dir_fn=lambda path: Path(path).mkdir(parents=True, exist_ok=True) or Path(path),
        content_renamer_cls=ContentRenamer,
        replace_content_fn=replace_text_content,
    )
    cleanup_rename(destination_root, mapping, replace_content_fn=replace_text_content)
    monkeypatch.syspath_prepend(str(destination_root / "src"))
    module_names = [
        destination, destination + "." + destination,
        destination + "." + destination + "_args",
        destination + "_worker", destination + "_worker." + destination + "_worker",
    ]
    for name in module_names:
        monkeypatch.delitem(sys.modules, name, raising=False)
    importlib.invalidate_caches()
    try:
        worker_module = importlib.import_module(
            f"{destination}_worker.{destination}_worker"
        )
        loaded = getattr(worker_module, destination_class + "Worker")
        assert loaded.manager_type.__name__ == destination_class
        assert loaded.manager_type.args_type.__name__ == destination_class + "Args"
        assert loaded.manager_type.typed_args.__name__ == destination_class + "ArgsTD"
        assert loaded.manager_type.args_type.value == 7
        for path in sorted(destination_root.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".toml"}:
                text = path.read_text(encoding="utf-8")
                remaining = text.replace(destination_class, "").replace(destination, "")
                assert source_class not in remaining
                assert source not in remaining
    finally:
        for name in module_names:
            sys.modules.pop(name, None)


def _clone_ignore_probe(source, destination, tmp_path):
    clone_project(
        source,
        destination,
        apps_path=tmp_path / "workspace",
        home_abs=tmp_path / "home",
        projects=[],
        logger=mock.Mock(),
        create_rename_map_fn=create_rename_map,
        clone_directory_fn=lambda src, dst, renames, spec, root: clone_directory(
            src,
            dst,
            renames,
            spec,
            root,
            ensure_dir_fn=lambda p: Path(p).mkdir(parents=True, exist_ok=True),
            content_renamer_cls=ContentRenamer,
            replace_content_fn=replace_text_content,
        ),
        cleanup_rename_fn=lambda root, renames: cleanup_rename(
            root,
            renames,
            replace_content_fn=replace_text_content,
        ),
    )


def test_clone_packaged_project_under_standard_uv_venv_keeps_payload(tmp_path):
    import subprocess
    import sys

    venv = tmp_path / "standard-uv-env"
    result = subprocess.run(
        ["uv", "venv", "--python", sys.executable, str(venv)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    ignore = venv / ".gitignore"
    original_ignore = ignore.read_bytes()
    assert b"*" in original_ignore
    source = venv / "lib" / "python3.13" / "site-packages" / "alpha_project"
    (source / "src" / "alpha").mkdir(parents=True)
    (source / "pyproject.toml").write_text('[project]\nname="alpha"\n')
    (source / "src" / "alpha" / "__init__.py").write_text("class Alpha: pass\n")
    (source / "data").mkdir()
    (source / "data" / "input.csv").write_text("value\n1\n")
    (source / ".gitignore").write_text("discard.txt\n")
    (source / "discard.txt").write_text("project-owned ignore")
    destination = tmp_path / "workspace" / "mission_2026_project"
    _clone_ignore_probe(source, destination, tmp_path)
    assert (destination / "pyproject.toml").is_file()
    assert (destination / "src" / "mission_2026" / "__init__.py").is_file()
    assert (destination / "data" / "input.csv").read_text() == "value\n1\n"
    assert not (destination / "discard.txt").exists()
    assert ignore.read_bytes() == original_ignore


def test_clone_uses_only_owning_repository_ignores_with_scoped_paths(tmp_path):
    (tmp_path / ".gitignore").write_text("*\n")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / ".gitignore").write_text("/unrelated.txt\napps/alpha_project/drop.txt\n")
    source = repo / "apps" / "alpha_project"
    source.mkdir(parents=True)
    for name in ["keep.txt", "unrelated.txt", "drop.txt", "own.txt"]:
        (source / name).write_text(name)
    (source / ".gitignore").write_text("own.txt\n")
    destination = tmp_path / "workspace" / "beta_project"
    _clone_ignore_probe(source, destination, tmp_path)
    assert (destination / "keep.txt").is_file()
    assert (destination / "unrelated.txt").is_file()
    assert not (destination / "drop.txt").exists()
    assert not (destination / "own.txt").exists()


def _scoped_ignore_project(tmp_path):
    (tmp_path / ".gitignore").write_text("*\n")
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".gitignore").write_text(
        "apps/alpha_project/repo.txt\napps/alpha_project/*.shared\n"
    )
    source = repo / "apps/alpha_project"
    (source / "data/nested").mkdir(parents=True)
    (source / ".gitignore").write_text(
        "own.txt\n!kept.shared\n/anchored.txt\n*.secret\nblocked/\n"
        "!blocked/keep.txt\ndata/*.drop\n"
    )
    (source / "data/.gitignore").write_text(
        "*.secret\n!keep.secret\n/anchored.txt\n!keep.drop\nclosed/\n"
    )
    (source / "data/nested/.gitignore").write_text(
        "!allowed.secret\n*.nested\n/local.txt\n"
    )
    decisions = {
        "keep.txt": None,
        "repo.txt": True,
        "own.txt": True,
        "lost.shared": True,
        "kept.shared": False,
        "anchored.txt": True,
        "data/token.secret": True,
        "data/keep.secret": False,
        "data/anchored.txt": True,
        "data/inner/anchored.txt": None,
        "data/drop.drop": True,
        "data/keep.drop": False,
        "data/nested/allowed.secret": False,
        "data/nested/token.secret": True,
        "data/nested/drop.nested": True,
        "data/nested/local.txt": True,
        "other/allowed.secret": True,
        "other/keep.txt": None,
        "blocked/keep.txt": True,
        "data/closed/token.txt": True,
        "build/output.txt": True,
        "dist/output.txt": True,
        "__pycache__/cached.pyc": True,
    }
    for name in decisions:
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("payload\n")
    return source, decisions


def test_clone_ignore_public_file_apis_share_scopes_and_tristate(tmp_path):
    source, expected = _scoped_ignore_project(tmp_path)
    spec = project_clone_support._ProjectCloneIgnoreSpec(source, mock.Mock())
    paths = [Path(name) for name in expected]
    checked = list(spec.check_files(paths))
    assert [result.file for result in checked] == paths
    assert [result.include for result in checked] == list(expected.values())
    for path, result in zip(paths, checked):
        single = spec.check_file(path)
        assert (single.include, single.index) == (result.include, result.index)
        assert spec.match_file(path) is bool(result.include)
        if result.index is not None:
            assert 0 <= result.index < len(spec.patterns)
    ignored = [path for path, include in zip(paths, expected.values()) if include]
    kept = [path for path, include in zip(paths, expected.values()) if not include]
    assert list(spec.match_files(iter(paths))) == ignored
    assert list(spec.match_files(iter(paths), negate=True)) == kept
    windows = [name.replace("/", "\\") for name in expected]
    assert [r.include for r in spec.check_files(windows, separators=("\\",))] == list(
        expected.values()
    )
    assert [spec.match_file(p, separators=("\\",)) for p in windows] == [
        bool(v) for v in expected.values()
    ]
    assert list(spec.match_files(windows, separators=("\\",))) == [
        name for name, include in zip(windows, expected.values()) if include
    ]
    assert spec.check_file("./data/keep.secret").include is False
    assert spec.check_file("data/closed/").include is True


@pytest.mark.parametrize(
    "api",
    [
        "match_files",
        "check_files",
        "match_tree_files",
        "check_tree_files",
        "match_entries",
        "match_tree_entries",
        "match_tree",
    ],
)
def test_clone_callback_bulk_and_tree_apis_obey_all_owned_ignores(tmp_path, api):
    import shutil
    from pathspec.util import iter_tree_entries

    source, expected = _scoped_ignore_project(tmp_path)
    destination = tmp_path / "workspace/beta_project"

    def callback(src, dst, renames, spec, root):
        files = sorted(
            p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file()
        )
        if api == "match_files":
            ignored = set(spec.match_files(iter(files)))
        elif api == "check_files":
            ignored = {r.file for r in spec.check_files(iter(files)) if r.include}
        elif api == "check_tree_files":
            ignored = {r.file for r in spec.check_tree_files(src) if r.include}
        elif api == "match_entries":
            ignored = {e.path for e in spec.match_entries(iter_tree_entries(src))}
        elif api == "match_tree_entries":
            ignored = {e.path for e in spec.match_tree_entries(src)}
        elif api == "match_tree":
            with pytest.warns(DeprecationWarning, match="match_tree"):
                ignored = set(spec.match_tree(src))
        else:
            ignored = set(getattr(spec, api)(src))
        for name in files:
            if name not in ignored:
                target = dst / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src / name, target)

    clone_project(
        source,
        destination,
        apps_path=tmp_path / "workspace",
        home_abs=tmp_path / "home",
        projects=[],
        logger=mock.Mock(),
        create_rename_map_fn=create_rename_map,
        clone_directory_fn=callback,
        cleanup_rename_fn=lambda *_: None,
    )
    for name, ignored in expected.items():
        assert (destination / name).is_file() is not bool(ignored), (api, name)


def test_recursive_clone_obeys_nested_rules_without_crossing_excluded_directories(
    tmp_path,
):
    source, expected = _scoped_ignore_project(tmp_path)
    destination = tmp_path / "workspace/beta_project"
    _clone_ignore_probe(source, destination, tmp_path)
    for name, ignored in expected.items():
        assert (destination / name).is_file() is not bool(ignored), name


def test_nested_ignore_exclusion_boundary_and_invalid_input_recovery(
    tmp_path, monkeypatch
):
    source = tmp_path / "project"
    (source / "data").mkdir(parents=True)
    (source / ".gitignore").write_text("root.txt\n")
    (source / "data/.gitignore").write_text("*.secret\n!keep.secret\n")
    spec = project_clone_support._ProjectCloneIgnoreSpec(source, mock.Mock())
    assert spec.check_file("data/token.secret").include is True
    assert spec.check_file("data/keep.secret").include is False
    for api in (spec.match_files, spec.check_files, spec.match_entries):
        with pytest.raises(TypeError):
            list(api("data/token.secret"))
    with pytest.raises(ValueError, match="within the source project"):
        spec.match_file("../external/secret.txt")
    assert spec.check_file("data/keep.secret").include is False
    assert spec.check_file("other/token.secret").include is None

    # An ignore file behind a symlink is outside the project's ignore authority.
    linked = source / "linked"
    linked.mkdir()
    (linked / ".gitignore").write_text("*\n")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda p: p == linked or original(p))
    assert spec.check_file("linked/keep.txt").include is None


def test_project_rule_cannot_reinclude_a_repository_excluded_parent(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / ".gitignore").write_text("apps/\n")
    source = repo / "apps/alpha_project"
    source.mkdir(parents=True)
    (source / ".gitignore").write_text("!keep.txt\n")
    spec = project_clone_support._ProjectCloneIgnoreSpec(source, mock.Mock())
    assert spec.check_file("keep.txt").include is True
