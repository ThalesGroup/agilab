from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from agi_env.pagelib_navigation_support import (
    active_app_candidates,
    build_project_selection,
    build_sidebar_dataframe_selection,
    normalize_query_param_value,
    resolve_default_selection,
    resolve_selected_df_path,
)
from agi_env.pagelib_selection_support import (
    on_df_change,
    resolve_active_app,
    select_project,
    sidebar_views,
)


class _State(dict):
    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name, value):
        self[name] = value


class _ProjectSidebar:
    def __init__(self, search_term: str, selection: str | None = None):
        self.search_term = search_term
        self.selection = selection
        self.infos: list[str] = []
        self.captions: list[str] = []
        self.select_calls: list[dict[str, object]] = []

    def text_input(self, *_args, **_kwargs):
        return self.search_term

    def info(self, message):
        self.infos.append(str(message))

    def caption(self, message):
        self.captions.append(str(message))

    def selectbox(self, label, options, index=0, key=None):
        self.select_calls.append(
            {"label": label, "options": list(options), "index": index, "key": key}
        )
        return self.selection if self.selection is not None else options[index]


class _Sidebar:
    def __init__(self, session_state):
        self.session_state = session_state

    def selectbox(self, _label, options, index=0, key=None, on_change=None):
        choice = options[index] if options else None
        if key is not None:
            self.session_state[key] = choice
        return choice


class _Logger:
    def __init__(self):
        self.messages: list[str] = []

    def info(self, message: str):
        self.messages.append(message)


def test_select_project_support_filters_shortlists_and_handles_empty_results():
    projects = [f"demo_{idx:03d}_project" for idx in range(60)]
    current = projects[-1]
    changed: list[str] = []
    sidebar = _ProjectSidebar("demo_", selection=projects[1])
    env = SimpleNamespace(
        apps_path=Path("/tmp/apps"),
        builtin_apps_path=Path("/tmp/apps/builtin"),
        projects=[],
        get_projects=lambda _apps, _builtin: projects,
    )

    select_project(
        ["ignored"],
        current,
        session_state={"env": env},
        sidebar=sidebar,
        build_project_selection_fn=build_project_selection,
        on_project_change_fn=lambda selection: changed.append(selection),
    )

    assert env.projects == projects
    assert sidebar.captions == ["Showing first 51 of 60 matches"]
    assert sidebar.select_calls[0]["index"] == 0
    shortlist = sidebar.select_calls[0]["options"]
    assert shortlist[0] == current
    assert len(shortlist) == 51
    assert changed == [projects[1]]

    empty_sidebar = _ProjectSidebar("zzz")
    select_project(
        projects[:3],
        current_project="",
        session_state={},
        sidebar=empty_sidebar,
        build_project_selection_fn=build_project_selection,
        on_project_change_fn=lambda _selection: (_ for _ in ()).throw(
            AssertionError("should not change")
        ),
    )

    assert empty_sidebar.infos == ["No projects match that filter."]
    assert empty_sidebar.select_calls == []


def test_select_project_support_survives_env_refresh_failure():
    sidebar = _ProjectSidebar("")
    env = SimpleNamespace(
        get_projects=lambda *_args: (_ for _ in ()).throw(RuntimeError("boom")),
        apps_path=Path("/apps"),
        builtin_apps_path=Path("/apps/builtin"),
    )

    select_project(
        ["alpha", "beta"],
        current_project="alpha",
        session_state={"env": env},
        sidebar=sidebar,
        build_project_selection_fn=build_project_selection,
        on_project_change_fn=lambda _selection: (_ for _ in ()).throw(
            AssertionError("should not change")
        ),
    )

    assert sidebar.infos == []


def test_sidebar_views_support_and_on_df_change_manage_selection_state(tmp_path):
    export_root = tmp_path / "export"
    lab_dir = export_root / "lab_a"
    lab_dir.mkdir(parents=True)
    default_df = lab_dir / "default_df"
    other_df = lab_dir / "other.csv"
    default_df.write_text("a\n1\n", encoding="utf-8")
    other_df.write_text("a\n2\n", encoding="utf-8")

    env = SimpleNamespace(AGILAB_EXPORT_ABS=export_root, target="lab_a")
    session_state = _State({"env": env})

    sidebar_views(
        session_state=session_state,
        sidebar=_Sidebar(session_state),
        scan_dir_fn=lambda _path: ["lab_a"],
        find_files_fn=lambda _path: [other_df, default_df],
        resolve_default_selection_fn=resolve_default_selection,
        build_sidebar_dataframe_selection_fn=build_sidebar_dataframe_selection,
        on_lab_change_fn=lambda *_args, **_kwargs: None,
        on_df_change_fn=lambda *_args, **_kwargs: None,
        path_cls=Path,
    )

    assert session_state["lab_dir"] == "lab_a"
    assert session_state["lab_dir_selectbox"] == "lab_a"
    assert session_state["module_path"] == Path("lab_a")
    assert session_state["df_file"] == export_root / Path("lab_a/default_df")
    assert session_state["index_page"] == Path("lab_a/default_df")

    stages_file = tmp_path / "stages" / "last.toml"
    loaded: list[tuple[Path, Path, str]] = []
    session_state["legacydf"] = "lab_a/other.csv"
    session_state["legacy"] = "cached"

    on_df_change(
        Path("lab_a"),
        Path("ignored.csv"),
        "legacy",
        stages_file,
        session_state=session_state,
        resolve_selected_df_path_fn=resolve_selected_df_path,
        load_last_stage_fn=lambda module_dir, stages_path, page_key: loaded.append(
            (module_dir, stages_path, page_key)
        ),
        logger=_Logger(),
        path_cls=Path,
    )

    assert session_state["legacydf_file"] == export_root / "lab_a/other.csv"
    assert session_state["df_file"] == export_root / "lab_a/other.csv"
    assert "legacy" not in session_state
    assert session_state["page_broken"] is True
    assert loaded == [(Path("lab_a"), stages_file, "legacy")]
    assert stages_file.parent.is_dir()


def test_sidebar_views_support_handles_empty_dataframe_list(tmp_path):
    export_root = tmp_path / "export"
    (export_root / "lab_a").mkdir(parents=True)
    env = SimpleNamespace(AGILAB_EXPORT_ABS=export_root, target="lab_a")
    session_state = _State({"env": env})

    sidebar_views(
        session_state=session_state,
        sidebar=_Sidebar(session_state),
        scan_dir_fn=lambda _path: ["lab_a"],
        find_files_fn=lambda _path: [],
        resolve_default_selection_fn=resolve_default_selection,
        build_sidebar_dataframe_selection_fn=build_sidebar_dataframe_selection,
        on_lab_change_fn=lambda *_args, **_kwargs: None,
        on_df_change_fn=lambda *_args, **_kwargs: None,
        path_cls=Path,
    )

    assert session_state["lab_dir"] == "lab_a"
    assert session_state["lab_dir_selectbox"] == "lab_a"
    assert session_state["df_files"] == []
    assert session_state["index_page"] == "lab_a"
    assert session_state["lab_adf"] is None
    assert session_state["df_file"] is None


def test_on_df_change_support_uses_explicit_df_file_when_no_selection(tmp_path):
    export_root = tmp_path / "export"
    export_root.mkdir()
    explicit_df = tmp_path / "absolute.csv"
    explicit_df.write_text("a\n1\n", encoding="utf-8")
    session_state = _State(
        {
            "env": SimpleNamespace(AGILAB_EXPORT_ABS=export_root),
            "legacy": "cached",
            "page_broken": False,
        }
    )

    on_df_change(
        Path("lab_a"),
        "legacy",
        df_file=explicit_df,
        stages_file=None,
        session_state=session_state,
        resolve_selected_df_path_fn=resolve_selected_df_path,
        load_last_stage_fn=lambda *_args, **_kwargs: None,
        logger=_Logger(),
        path_cls=Path,
    )

    assert session_state["legacydf_file"] == explicit_df
    assert session_state["df_file"] == explicit_df
    assert "legacy" not in session_state
    assert session_state["page_broken"] is True


def test_resolve_active_app_support_prefers_query_param_and_fallback_last_app(tmp_path):
    apps_root = tmp_path / "apps"
    builtin_root = apps_root / "builtin"
    target = builtin_root / "flight_telemetry_project"
    target.mkdir(parents=True)
    changed_to: list[Path] = []
    stored: list[Path] = []

    env = SimpleNamespace(
        apps_path=apps_root,
        app="mycode_project",
        projects=["flight_telemetry_project"],
        active_app=apps_root / "mycode_project",
        change_app=lambda path: changed_to.append(path)
        or setattr(env, "active_app", path)
        or setattr(env, "app", path.name),
    )

    app_name, changed = resolve_active_app(
        env,
        query_params={"active_app": "flight"},
        normalize_query_param_value_fn=normalize_query_param_value,
        active_app_candidates_fn=active_app_candidates,
        store_last_active_app_fn=lambda path: stored.append(path),
        load_last_active_app_fn=lambda: None,
    )

    assert changed is True
    assert app_name == "flight_telemetry_project"
    assert changed_to == [target]
    assert stored == [target]

    last_app = apps_root / "demo_project"
    last_app.mkdir(parents=True)
    env.app = "flight_telemetry_project"
    env.active_app = target
    changed_to.clear()
    app_name, changed = resolve_active_app(
        env,
        query_params={},
        normalize_query_param_value_fn=normalize_query_param_value,
        active_app_candidates_fn=active_app_candidates,
        store_last_active_app_fn=lambda _path: None,
        load_last_active_app_fn=lambda: last_app,
    )

    assert changed is True
    assert app_name == "demo_project"
    assert changed_to == [last_app]


def test_resolve_active_app_support_skips_bad_requested_candidate_and_failed_last_app(tmp_path):
    requested_path = tmp_path / "requested"
    requested_path.mkdir()
    last_app = tmp_path / "last_app"
    last_app.mkdir()
    change_attempts: list[Path] = []

    def _change_app(path):
        change_attempts.append(Path(path))
        raise RuntimeError("bad switch")

    env = SimpleNamespace(
        app="current",
        apps_path=tmp_path,
        projects=["requested"],
        active_app=tmp_path / "current_app",
        change_app=_change_app,
    )

    name, changed = resolve_active_app(
        env,
        query_params={"active_app": "requested"},
        normalize_query_param_value_fn=normalize_query_param_value,
        active_app_candidates_fn=active_app_candidates,
        store_last_active_app_fn=lambda _path: None,
        load_last_active_app_fn=lambda: last_app,
    )

    assert name == "current"
    assert changed is False
    assert change_attempts

    change_attempts.clear()
    name, changed = resolve_active_app(
        env,
        query_params={},
        normalize_query_param_value_fn=normalize_query_param_value,
        active_app_candidates_fn=active_app_candidates,
        store_last_active_app_fn=lambda _path: None,
        load_last_active_app_fn=lambda: last_app,
    )
    assert name == "current"
    assert changed is False
    assert change_attempts == [last_app]
