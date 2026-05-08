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
        get_projects=lambda *args: ["sb3_trainer_project", "network_sim_project", "Alpha_project", "sb3_trainer_project"],
    )

    modules = pipeline_sidebar.available_lab_modules(env, tmp_path / "export")

    assert modules == ["Alpha_project", "network_sim_project", "sb3_trainer_project"]


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


def test_load_last_active_app_name_returns_none_when_missing_or_unknown(monkeypatch):
    monkeypatch.setattr(pipeline_sidebar, "load_last_active_app", lambda: None)
    assert pipeline_sidebar.load_last_active_app_name(["demo_project"]) is None

    monkeypatch.setattr(pipeline_sidebar, "load_last_active_app", lambda: Path("/"))
    assert pipeline_sidebar.load_last_active_app_name(["demo_project"]) is None

    monkeypatch.setattr(
        pipeline_sidebar,
        "load_last_active_app",
        lambda: Path("/tmp/apps/unknown_project"),
    )
    assert pipeline_sidebar.load_last_active_app_name(["demo_project"]) is None


def test_available_lab_modules_falls_back_to_export_scan(monkeypatch, tmp_path):
    export_root = tmp_path / "export"

    env = SimpleNamespace(
        apps_path=tmp_path / "apps",
        builtin_apps_path=tmp_path / "builtin",
        apps_repository_root=tmp_path,
        get_projects=lambda *args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(pipeline_sidebar, "scan_dir", lambda path: ["beta", "alpha", "alpha"])

    modules = pipeline_sidebar.available_lab_modules(env, export_root)

    assert modules == ["alpha", "beta"]


def test_available_lab_modules_drops_blank_projects_and_empty_scan(monkeypatch, tmp_path):
    env = SimpleNamespace(
        apps_path=tmp_path / "apps",
        builtin_apps_path=tmp_path / "builtin",
        apps_repository_root=tmp_path,
        get_projects=lambda *args: ["", " demo_project ", " "],
    )

    modules = pipeline_sidebar.available_lab_modules(env, tmp_path / "export")
    assert modules == ["demo_project"]

    env = SimpleNamespace(
        apps_path=tmp_path / "apps",
        builtin_apps_path=tmp_path / "builtin",
        apps_repository_root=tmp_path,
        get_projects=lambda *args: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    monkeypatch.setattr(pipeline_sidebar, "scan_dir", lambda _path: ["", "  "])

    modules = pipeline_sidebar.available_lab_modules(env, tmp_path / "export")
    assert modules == []


def test_available_lab_modules_reraises_unexpected_value_error(tmp_path):
    env = SimpleNamespace(
        apps_path=tmp_path / "apps",
        builtin_apps_path=tmp_path / "builtin",
        apps_repository_root=tmp_path,
        get_projects=lambda *args: (_ for _ in ()).throw(ValueError("bad project config")),
    )

    try:
        pipeline_sidebar.available_lab_modules(env, tmp_path / "export")
    except ValueError as exc:
        assert str(exc) == "bad project config"
    else:
        raise AssertionError("ValueError should propagate for unexpected project listing failures")


def test_on_lab_change_updates_session_state_and_stores_last_app(monkeypatch, tmp_path):
    app_root = tmp_path / "apps"
    project_dir = app_root / "sb3_trainer_project"
    project_dir.mkdir(parents=True)

    stored: list[Path] = []
    fake_st = SimpleNamespace(session_state=_SessionState(index_page="old_project", stages_file="x", df_file="y"))

    monkeypatch.setattr(pipeline_sidebar, "st", fake_st)
    monkeypatch.setattr(pipeline_sidebar, "store_last_active_app", lambda path: stored.append(path))

    env = SimpleNamespace(apps_path=app_root)
    fake_st.session_state["env"] = env

    pipeline_sidebar.on_lab_change("sb3_trainer_project")

    assert fake_st.session_state["lab_dir"] == "sb3_trainer_project"
    assert fake_st.session_state["project_changed"] is True
    assert fake_st.session_state["_experiment_reload_required"] is True
    assert fake_st.session_state["page_broken"] is True
    assert "stages_file" not in fake_st.session_state
    assert "df_file" not in fake_st.session_state
    assert stored == [project_dir]


def test_on_lab_change_checks_builtin_path_and_swallows_env_errors(monkeypatch, tmp_path):
    builtin_project_dir = tmp_path / "apps" / "builtin" / "demo_project"
    builtin_project_dir.mkdir(parents=True)

    stored: list[Path] = []
    fake_st = SimpleNamespace(session_state=_SessionState(index_page="demo", demodf="remove-me"))
    monkeypatch.setattr(pipeline_sidebar, "st", fake_st)
    monkeypatch.setattr(pipeline_sidebar, "store_last_active_app", lambda path: stored.append(path))

    fake_st.session_state["env"] = SimpleNamespace(apps_path=tmp_path / "apps")
    pipeline_sidebar.on_lab_change("demo_project")

    assert "demodf" not in fake_st.session_state
    assert stored == [builtin_project_dir]

    fake_st = SimpleNamespace(session_state=_SessionState(index_page="demo"))
    monkeypatch.setattr(pipeline_sidebar, "st", fake_st)
    fake_st.session_state["env"] = SimpleNamespace()
    pipeline_sidebar.on_lab_change("demo_project")
    assert fake_st.session_state["lab_dir"] == "demo_project"


def test_on_lab_change_swallows_store_last_active_app_os_error(monkeypatch, tmp_path):
    app_root = tmp_path / "apps"
    project_dir = app_root / "demo_project"
    project_dir.mkdir(parents=True)

    fake_st = SimpleNamespace(session_state=_SessionState(index_page="demo"))
    monkeypatch.setattr(pipeline_sidebar, "st", fake_st)
    monkeypatch.setattr(
        pipeline_sidebar,
        "store_last_active_app",
        lambda _path: (_ for _ in ()).throw(OSError("disk error")),
    )
    fake_st.session_state["env"] = SimpleNamespace(apps_path=app_root)

    pipeline_sidebar.on_lab_change("demo_project")

    assert fake_st.session_state["lab_dir"] == "demo_project"
    assert fake_st.session_state["project_changed"] is True


def test_normalize_lab_choice_handles_empty_and_stem_matches():
    assert pipeline_sidebar.normalize_lab_choice("", ["demo_project"]) == ""
    assert pipeline_sidebar.normalize_lab_choice("demo", []) == ""
    assert (
        pipeline_sidebar.normalize_lab_choice("/tmp/work/demo_project", ["demo_project", "other_project"])
        == "demo_project"
    )
    assert (
        pipeline_sidebar.normalize_lab_choice("/tmp/work/demo", ["demo_project", "other_project"])
        == "demo_project"
    )


def test_normalize_lab_choice_matches_module_by_stem_only_and_returns_empty_for_unmatched():
    assert pipeline_sidebar.normalize_lab_choice("/tmp/work/demo_project", ["demo"]) == "demo"
    assert pipeline_sidebar.normalize_lab_choice("/tmp/work/missing_project", ["demo"]) == ""


def test_resolve_lab_export_dir_handles_blank_and_missing_candidates(tmp_path):
    export_root = tmp_path / "export"
    export_root.mkdir()

    assert pipeline_sidebar.resolve_lab_export_dir(export_root, "") == export_root.resolve()
    assert (
        pipeline_sidebar.resolve_lab_export_dir(export_root, "demo_project")
        == (export_root / "demo").resolve()
    )


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
