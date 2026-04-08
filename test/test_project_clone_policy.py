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
