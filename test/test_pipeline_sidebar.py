from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


def _load_module(module_name: str, relative_path: str):
    module_path = Path(relative_path)
    importlib.invalidate_caches()
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


pipeline_sidebar = _load_module("agilab.pipeline_sidebar", "src/agilab/pipeline_sidebar.py")


def test_load_last_active_app_name_normalizes_project_suffix(monkeypatch):
    monkeypatch.setattr(
        pipeline_sidebar,
        "load_last_active_app",
        lambda: Path("/tmp/sb3_trainer_project"),
    )

    resolved = pipeline_sidebar.load_last_active_app_name(["sb3_trainer", "network_sim"])

    assert resolved == "sb3_trainer"


def test_available_lab_modules_uses_env_projects_before_export_scan(tmp_path):
    env = SimpleNamespace(
        apps_path=tmp_path / "apps",
        builtin_apps_path=tmp_path / "builtin",
        apps_repository_root=tmp_path,
        get_projects=lambda *args: ["sb3_trainer_project", "network_sim_project", "sb3_trainer_project"],
    )

    modules = pipeline_sidebar.available_lab_modules(env, tmp_path / "export")

    assert modules == ["sb3_trainer_project", "network_sim_project"]


def test_normalize_lab_choice_and_export_resolution(tmp_path):
    export_root = tmp_path / "export"
    export_dir = export_root / "sb3_trainer"
    export_dir.mkdir(parents=True)

    normalized = pipeline_sidebar.normalize_lab_choice(
        "sb3_trainer",
        ["sb3_trainer_project", "network_sim_project"],
    )
    resolved = pipeline_sidebar.resolve_lab_export_dir(export_root, normalized)

    assert normalized == "sb3_trainer_project"
    assert resolved == export_dir.resolve()

