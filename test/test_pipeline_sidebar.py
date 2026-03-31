from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


class _SessionState(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


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


def test_load_last_active_app_name_accepts_path_string(monkeypatch):
    monkeypatch.setattr(
        pipeline_sidebar,
        "load_last_active_app",
        lambda: Path("/tmp/apps/network_sim_project"),
    )

    resolved = pipeline_sidebar.load_last_active_app_name(["sb3_trainer_project", "network_sim_project"])

    assert resolved == "network_sim_project"


def test_available_lab_modules_falls_back_to_export_scan(monkeypatch, tmp_path):
    export_root = tmp_path / "export"

    env = SimpleNamespace(
        apps_path=tmp_path / "apps",
        builtin_apps_path=tmp_path / "builtin",
        apps_repository_root=tmp_path,
        get_projects=lambda *args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(pipeline_sidebar, "scan_dir", lambda path: ["alpha", "beta", "alpha"])

    modules = pipeline_sidebar.available_lab_modules(env, export_root)

    assert modules == ["alpha", "beta"]


def test_on_lab_change_updates_session_state_and_stores_last_app(monkeypatch, tmp_path):
    app_root = tmp_path / "apps"
    project_dir = app_root / "sb3_trainer_project"
    project_dir.mkdir(parents=True)

    stored: list[Path] = []
    fake_st = SimpleNamespace(session_state=_SessionState(index_page="old_project", steps_file="x", df_file="y"))

    monkeypatch.setattr(pipeline_sidebar, "st", fake_st)
    monkeypatch.setattr(pipeline_sidebar, "store_last_active_app", lambda path: stored.append(path))

    env = SimpleNamespace(apps_path=app_root)
    fake_st.session_state["env"] = env

    pipeline_sidebar.on_lab_change("sb3_trainer_project")

    assert fake_st.session_state["lab_dir"] == "sb3_trainer_project"
    assert fake_st.session_state["project_changed"] is True
    assert fake_st.session_state["_experiment_reload_required"] is True
    assert fake_st.session_state["page_broken"] is True
    assert "steps_file" not in fake_st.session_state
    assert "df_file" not in fake_st.session_state
    assert stored == [project_dir]


def test_open_notebook_in_browser_injects_expected_url(monkeypatch):
    captured: list[tuple[str, int, int]] = []
    fake_components = SimpleNamespace(v1=SimpleNamespace(html=lambda html, height, width: captured.append((html, height, width))))
    fake_st = SimpleNamespace(components=fake_components)

    monkeypatch.setattr(pipeline_sidebar, "st", fake_st)

    pipeline_sidebar.open_notebook_in_browser()

    assert len(captured) == 1
    html, height, width = captured[0]
    assert pipeline_sidebar.JUPYTER_URL in html
    assert height == 0
    assert width == 0
