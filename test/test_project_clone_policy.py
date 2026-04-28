from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


MODULE_PATH = Path("src/agilab/pages/1_▶️ PROJECT.py")


def _load_project_module():
    spec = importlib.util.spec_from_file_location("agilab_project_page_tests", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_finalize_cloned_project_environment_detaches_shared_venv(tmp_path: Path):
    module = _load_project_module()
    source_root = tmp_path / "source_project"
    dest_root = tmp_path / "clone_project"
    source_venv = source_root / ".venv"
    dest_venv = dest_root / ".venv"
    source_venv.mkdir(parents=True)
    dest_root.mkdir(parents=True)
    os.symlink(source_venv, dest_venv, target_is_directory=True)

    message = module._finalize_cloned_project_environment(
        source_root,
        dest_root,
        "detach_venv",
    )

    assert message is not None
    assert "without sharing" in message
    assert not dest_venv.exists()
    assert not dest_venv.is_symlink()


def test_finalize_cloned_project_environment_keeps_shared_venv(tmp_path: Path):
    module = _load_project_module()
    source_root = tmp_path / "source_project"
    dest_root = tmp_path / "clone_project"
    source_venv = source_root / ".venv"
    dest_venv = dest_root / ".venv"
    source_venv.mkdir(parents=True)
    dest_root.mkdir(parents=True)
    os.symlink(source_venv, dest_venv, target_is_directory=True)

    message = module._finalize_cloned_project_environment(
        source_root,
        dest_root,
        "share_source_venv",
    )

    assert message is not None
    assert "shares the source .venv" in message
    assert dest_venv.is_symlink()


def test_repair_renamed_project_environment_moves_real_venv(tmp_path: Path):
    module = _load_project_module()
    source_root = tmp_path / "source_project"
    dest_root = tmp_path / "renamed_project"
    source_venv = source_root / ".venv"
    dest_venv = dest_root / ".venv"
    source_venv.mkdir(parents=True)
    dest_root.mkdir(parents=True)
    (source_venv / "marker.txt").write_text("ok", encoding="utf-8")
    os.symlink(source_venv, dest_venv, target_is_directory=True)

    message = module._repair_renamed_project_environment(source_root, dest_root)

    assert message is not None
    assert "Preserved the project .venv" in message
    assert not source_venv.exists()
    assert not source_venv.is_symlink()
    assert (dest_venv / "marker.txt").read_text(encoding="utf-8") == "ok"


def test_create_project_clone_action_creates_project_and_reports_strategy(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []

    def _clone_project(source: Path, target: Path):
        clone_calls.append((source, target))
        (tmp_path / target).mkdir()

    env = SimpleNamespace(apps_path=tmp_path, clone_project=_clone_project)

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="New Demo",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "success"
    assert result.title == "Project 'new_demo_project' created."
    assert result.detail is not None
    assert "without sharing" in result.detail
    assert result.data["new_name"] == "new_demo_project"
    assert clone_calls == [(Path("source_project"), Path("new_demo_project"))]
    assert (tmp_path / "new_demo_project").is_dir()


def test_create_project_clone_action_rejects_duplicate_names(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []
    (tmp_path / "existing_project").mkdir()
    env = SimpleNamespace(
        apps_path=tmp_path,
        clone_project=lambda source, target: clone_calls.append((source, target)),
    )

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="Existing",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "warning"
    assert result.title == "Project 'existing_project' already exists."
    assert result.next_action is not None
    assert "Choose another project name" in result.next_action
    assert clone_calls == []


def test_create_project_clone_action_reports_missing_clone_output(tmp_path: Path):
    module = _load_project_module()
    env = SimpleNamespace(apps_path=tmp_path, clone_project=lambda _source, _target: None)

    result = module._create_project_clone_action(
        env,
        clone_source="source_project",
        raw_project_name="Missing Output",
        clone_env_strategy="detach_venv",
    )

    assert result.status == "error"
    assert result.title == "Error while creating 'missing_output_project'."
    assert result.next_action is not None
    assert "filesystem permissions" in result.next_action


def test_rename_project_action_preserves_venv_and_removes_source(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []
    source_root = tmp_path / "current_project"
    source_venv = source_root / ".venv"
    source_venv.mkdir(parents=True)
    (source_venv / "marker.txt").write_text("ok", encoding="utf-8")

    def _clone_project(source: Path, target: Path):
        clone_calls.append((source, target))
        (tmp_path / target).mkdir()

    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=_clone_project,
    )

    result = module._rename_project_action(env, raw_project_name="Renamed")

    assert result.status == "success"
    assert result.title == "Project renamed: 'current_project' -> 'renamed_project'"
    assert result.detail is not None
    assert "Preserved the project .venv" in result.detail
    assert result.next_action is None
    assert result.data["new_name"] == "renamed_project"
    assert clone_calls == [(Path("current_project"), Path("renamed_project"))]
    assert not source_root.exists()
    assert (tmp_path / "renamed_project/.venv/marker.txt").read_text(encoding="utf-8") == "ok"


def test_rename_project_action_rejects_duplicate_target(tmp_path: Path):
    module = _load_project_module()
    clone_calls: list[tuple[Path, Path]] = []
    (tmp_path / "existing_project").mkdir()
    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=lambda source, target: clone_calls.append((source, target)),
    )

    result = module._rename_project_action(env, raw_project_name="Existing")

    assert result.status == "warning"
    assert result.title == "Project 'existing_project' already exists."
    assert result.next_action is not None
    assert "Choose another project name" in result.next_action
    assert clone_calls == []


def test_rename_project_action_reports_missing_clone_output(tmp_path: Path):
    module = _load_project_module()
    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=lambda _source, _target: None,
    )

    result = module._rename_project_action(env, raw_project_name="Missing Output")

    assert result.status == "error"
    assert result.title == "Error: Project 'missing_output_project' not found after renaming."
    assert result.next_action is not None
    assert "filesystem permissions" in result.next_action


def test_rename_project_action_reports_source_cleanup_failure(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    source_root = tmp_path / "current_project"
    source_root.mkdir()

    def _clone_project(_source: Path, target: Path):
        (tmp_path / target).mkdir()

    def _fail_rmtree(_path: Path):
        raise OSError("locked")

    monkeypatch.setattr(module.shutil, "rmtree", _fail_rmtree)
    env = SimpleNamespace(
        app="current_project",
        apps_path=tmp_path,
        clone_project=_clone_project,
    )

    result = module._rename_project_action(env, raw_project_name="Renamed")

    assert result.status == "success"
    assert result.detail is not None
    assert "failed to remove" in result.detail
    assert result.next_action == f"Remove the old project directory manually: {source_root}"


def test_safe_remove_path_collects_probe_errors(monkeypatch):
    module = _load_project_module()
    errors: list[str] = []

    class _BrokenPath:
        def __init__(self, _value):
            pass

        def exists(self):
            raise OSError("probe failed")

        def is_symlink(self):
            return False

    monkeypatch.setattr(module, "Path", _BrokenPath)

    module._safe_remove_path("/tmp/demo", "demo", errors)

    assert errors == ["demo: probe failed"]


def test_regex_replace_rewrites_matching_file(tmp_path: Path):
    module = _load_project_module()
    target = tmp_path / "folders.xml"
    target.write_text('<folder name="demo" />\n', encoding="utf-8")
    errors: list[str] = []

    module._regex_replace(target, r'<folder name="demo" />', "", "folders", errors)

    assert target.read_text(encoding="utf-8") == "\n"
    assert errors == []


def test_regex_replace_reports_decode_errors(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    target = tmp_path / "folders.xml"
    target.write_text("demo", encoding="utf-8")
    errors: list[str] = []

    original_read_text = Path.read_text

    def _raise_decode(self, *args, **kwargs):
        if self == target:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad data")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_decode)

    module._regex_replace(target, "demo", "fixed", "folders", errors)

    assert errors == ["folders: 'utf-8' codec can't decode byte 0xff in position 0: bad data"]


def test_cleanup_run_configuration_artifacts_removes_matching_files(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    run_dir = tmp_path / ".idea" / "runConfigurations"
    run_dir.mkdir(parents=True)
    keep_xml = run_dir / "keep.xml"
    keep_xml.write_text('<config name="keep" />\n', encoding="utf-8")
    remove_by_pattern = run_dir / "_demo_clone.xml"
    remove_by_pattern.write_text('<config name="demo" />\n', encoding="utf-8")
    remove_by_content = run_dir / "manual.xml"
    remove_by_content.write_text('<config app="demo_app" />\n', encoding="utf-8")
    folders_xml = run_dir / "folders.xml"
    folders_xml.write_text('<folder name="demo_app" />\n<folder name="keep" />\n', encoding="utf-8")
    errors: list[str] = []

    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)

    module._cleanup_run_configuration_artifacts("demo_app", "demo_clone", errors)

    assert not remove_by_pattern.exists()
    assert not remove_by_content.exists()
    assert keep_xml.exists()
    assert '<folder name="demo_app" />' not in folders_xml.read_text(encoding="utf-8")
    assert errors == []


def test_process_files_reports_decode_errors(tmp_path: Path, monkeypatch):
    module = _load_project_module()
    source_app = tmp_path / "demo_app"
    target_app = tmp_path / "demo_clone"
    source_app.mkdir()
    source_file = source_app / "broken.py"
    source_file.write_text("print('demo')\n", encoding="utf-8")
    warnings: list[str] = []

    original_read_text = Path.read_text

    def _raise_decode(self, *args, **kwargs):
        if self == source_file:
            raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad data")
        return original_read_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", _raise_decode)
    monkeypatch.setattr(module.st, "warning", warnings.append)

    spec = module.PathSpec.from_lines(module.GitWildMatchPattern, [])
    module.process_files(
        str(source_app),
        ["broken.py"],
        source_app,
        {"demo_app": "demo_clone"},
        spec,
    )

    assert warnings == [
        "Error processing file 'broken.py': 'utf-8' codec can't decode byte 0xff in position 0: bad data"
    ]
    assert not (target_app / "broken.py").exists()


def test_extract_attributes_code_handles_module_level_and_class_scope():
    module = _load_project_module()
    parsed = module.ast.parse(
        "GLOBAL = 1\nclass Demo:\n    value = 2\n    other: int = 3\n"
    )

    class_attributes = module._extract_attributes_code(parsed, "Demo")
    module_attributes = module._extract_attributes_code(parsed, "module-level")

    assert "value = 2" in class_attributes
    assert "other: int = 3" in class_attributes
    assert "GLOBAL = 1" in module_attributes


def test_build_updated_attributes_source_rewrites_selected_class():
    module = _load_project_module()
    original = "class Demo:\n    value = 1\n"

    updated = module._build_updated_attributes_source(
        original,
        "value = 4\nother = 5\n",
        "Demo",
    )

    assert "value = 4" in updated
    assert "other = 5" in updated
    assert "value = 1" not in updated


def test_build_updated_function_source_rejects_non_function_code():
    module = _load_project_module()

    with pytest.raises(ValueError, match="must define a function or method"):
        module._build_updated_function_source(
            "def demo():\n    return 1\n",
            "value = 2\n",
            "demo",
            "module-level",
        )
