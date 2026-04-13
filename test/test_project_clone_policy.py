from __future__ import annotations

import importlib.util
import os
from pathlib import Path


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
