from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import warnings

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

PAGE_PATH = "src/agilab/apps-pages/view_maps/src/view_maps/view_maps.py"
MODULE_PATH = Path(PAGE_PATH)


def _suppress_page_import_warnings() -> None:
    warnings.filterwarnings(
        "ignore",
        message=r".*ast\.Num is deprecated and will be removed in Python 3\.14.*",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"Theme names and color schemes are lowercase in IPython 9\.0 use nocolor instead",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"'oneOf' deprecated - use 'one_of'",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"'parseString' deprecated - use 'parse_string'",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"'resetCache' deprecated - use 'reset_cache'",
        category=DeprecationWarning,
    )
    warnings.filterwarnings(
        "ignore",
        message=r"'enablePackrat' deprecated - use 'enable_packrat'",
        category=DeprecationWarning,
    )


class _State(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, item, value):
        self[item] = value


class _StopExecution(RuntimeError):
    pass


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeColumn(_NullContext):
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def number_input(self, label, *args, key=None, value=None, **kwargs):
        default = value
        if default is None:
            default = kwargs.get("min_value")
        return self._streamlit._widget_value(
            "column.number_input",
            label,
            key=key,
            default=default,
        )


class _FakeSidebar(_NullContext):
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def text_input(self, label, *args, key=None, **kwargs):
        default = self._streamlit.session_state.get(key, "")
        return self._streamlit._widget_value("sidebar.text_input", label, key=key, default=default)

    def selectbox(self, label, options, *args, key=None, index=0, **kwargs):
        default = options[index] if options else None
        return self._streamlit._widget_value(
            "sidebar.selectbox",
            label,
            key=key,
            default=default,
            options=options,
        )

    def radio(self, label, options, *args, key=None, index=0, **kwargs):
        default = options[index] if options else None
        return self._streamlit._widget_value(
            "sidebar.radio",
            label,
            key=key,
            default=default,
            options=options,
        )

    def multiselect(self, label, options, *args, key=None, **kwargs):
        default = list(self._streamlit.session_state.get(key, []))
        return self._streamlit._widget_value(
            "sidebar.multiselect",
            label,
            key=key,
            default=default,
            options=options,
        )

    def checkbox(self, label, *args, key=None, value=False, **kwargs):
        return self._streamlit._widget_value(
            "sidebar.checkbox",
            label,
            key=key,
            default=value,
        )

    def number_input(self, label, *args, key=None, value=None, **kwargs):
        default = value if value is not None else kwargs.get("min_value")
        return self._streamlit._widget_value(
            "sidebar.number_input",
            label,
            key=key,
            default=default,
        )

    def button(self, label, *args, key=None, disabled=False, **kwargs):
        return self._streamlit._widget_value(
            "sidebar.button",
            label,
            key=key,
            default=False,
        )

    def caption(self, message):
        self._streamlit.calls["sidebar.caption"].append(message)

    def error(self, message):
        self._streamlit.calls["sidebar.error"].append(message)

    def warning(self, message):
        self._streamlit.calls["sidebar.warning"].append(message)

    def write(self, *args, **kwargs):
        self._streamlit.calls["sidebar.write"].append(" ".join(str(arg) for arg in args))

    def expander(self, *args, **kwargs):
        return _NullContext()


class _FakeStreamlit:
    def __init__(self, widget_values: dict | None = None):
        self.session_state = _State({"GUI_SAMPLING": 1, "TABLE_MAX_ROWS": 5})
        self.sidebar = _FakeSidebar(self)
        self.widget_values = widget_values or {}
        self.calls = {
            "title": [],
            "info": [],
            "warning": [],
            "error": [],
            "caption": [],
            "write": [],
            "code": [],
            "dataframe": [],
            "plotly_chart": [],
            "sidebar.caption": [],
            "sidebar.error": [],
            "sidebar.warning": [],
            "sidebar.write": [],
        }

    def _widget_value(self, kind, label, key=None, default=None, options=None):
        candidates = [
            (kind, key),
            (kind, label),
            (key,),
            (label,),
            kind,
        ]
        value = None
        for candidate in candidates:
            if candidate in self.widget_values:
                value = self.widget_values[candidate]
                break
        if value is None:
            value = default
        if callable(value):
            value = value(label=label, key=key, options=options, default=default)
        if key is not None:
            self.session_state[key] = value
        return value

    def title(self, message, *args, **kwargs):
        self.calls["title"].append(message)

    def info(self, message, *args, **kwargs):
        self.calls["info"].append(message)

    def warning(self, message, *args, **kwargs):
        self.calls["warning"].append(message)

    def error(self, message, *args, **kwargs):
        self.calls["error"].append(message)

    def caption(self, message, *args, **kwargs):
        self.calls["caption"].append(message)

    def write(self, *args, **kwargs):
        self.calls["write"].append(" ".join(str(arg) for arg in args))

    def code(self, message, *args, **kwargs):
        self.calls["code"].append(message)

    def dataframe(self, *args, **kwargs):
        self.calls["dataframe"].append((args, kwargs))

    def plotly_chart(self, *args, **kwargs):
        self.calls["plotly_chart"].append((args, kwargs))

    def selectbox(self, label, options, *args, key=None, index=0, **kwargs):
        default = options[index] if options else None
        return self._widget_value("selectbox", label, key=key, default=default, options=options)

    def expander(self, *args, **kwargs):
        return _NullContext()

    def columns(self, count):
        return [_FakeColumn(self) for _ in range(count)]

    def slider(self, label, *args, key=None, value=None, **kwargs):
        default = value
        if default is None:
            default = kwargs.get("min_value")
        return self._widget_value("slider", label, key=key, default=default)

    def stop(self):
        raise _StopExecution()


def _load_view_maps_module():
    spec = importlib.util.spec_from_file_location("view_maps_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with warnings.catch_warnings():
        _suppress_page_import_warnings()
        with patch("streamlit.title", lambda *args, **kwargs: None):
            spec.loader.exec_module(module)
    return module


def _make_env(tmp_path: Path, datadir: Path, *, app_name: str = "demo_map_project") -> SimpleNamespace:
    settings_file = tmp_path / app_name / "src" / "app_settings.toml"
    settings_file.parent.mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        target="demo_map",
        projects=["demo_map_project"],
        app=app_name,
        AGILAB_EXPORT_ABS=str(tmp_path / "export"),
        app_settings_file=settings_file,
        TABLE_MAX_ROWS=5,
        GUI_SAMPLING=1,
        is_source_env=True,
        is_worker_env=False,
    )


def test_view_maps_renders_minimal_export_dataset(tmp_path, monkeypatch) -> None:
    apps_dir = tmp_path / "apps"
    apps_dir.mkdir()
    project_dir = apps_dir / "demo_map_project"
    (project_dir / "src" / "demo_map").mkdir(parents=True)
    (project_dir / "pyproject.toml").write_text("[project]\nname='demo-map-project'\n", encoding="utf-8")
    dataset_dir = tmp_path / "export" / "demo_map"
    dataset_dir.mkdir(parents=True)
    (dataset_dir / "export.csv").write_text(
        "lat,long,beam,alt_m\n"
        "48.8566,2.3522,A,1200\n"
        "43.6045,1.4440,B,1250\n"
        "45.7640,4.8357,A,1300\n",
        encoding="utf-8",
    )
    (project_dir / "src" / "app_settings.toml").write_text(
        "[view_maps]\n"
        f"datadir = \"{dataset_dir.as_posix()}\"\n"
        "file_ext_choice = \"all\"\n"
        "df_select_mode = \"Single file\"\n",
        encoding="utf-8",
    )
    (project_dir / "src" / "demo_map" / "__init__.py").write_text("", encoding="utf-8")

    argv = [Path(PAGE_PATH).name, "--active-app", str(project_dir)]
    with patch.object(sys, "argv", argv):
        monkeypatch.setenv("AGI_EXPORT_DIR", str(tmp_path / "export"))
        monkeypatch.setenv("AGI_LOCAL_SHARE", str(tmp_path / "localshare"))
        monkeypatch.setenv("AGI_CLUSTER_SHARE", str(tmp_path / "clustershare"))
        monkeypatch.setenv("OPENAI_API_KEY", "dummy")
        monkeypatch.setenv("IS_SOURCE_ENV", "1")
        at = AppTest.from_file(PAGE_PATH, default_timeout=20)
        at.run()

    assert not at.exception
    assert any("Cartography Visualisation" in title.value for title in at.title)
    assert any(widget.label == "Dataset selection" for widget in at.radio)
    assert any(widget.label == "File type" for widget in at.selectbox)
    assert any(widget.label == "DataFrame" for widget in at.selectbox)
    assert at.session_state["datadir"] == str(dataset_dir)
    assert at.session_state["file_ext_choice"] == "all"
    assert at.session_state["df_select_mode"] == "Single file"
    assert [path.name for path in at.session_state["dataset_files"]] == ["export.csv"]
    assert at.session_state["view_maps:df_files_selected"] == ["export.csv"]


def test_view_maps_filters_hidden_dataset_files() -> None:
    module = _load_view_maps_module()
    datadir = Path("/tmp/demo-datasets")

    files = [
        datadir / "visible.csv",
        datadir / ".hidden.csv",
        datadir / "nested" / ".shadow" / "ignored.parquet",
        Path("/elsewhere/outside.json"),
    ]

    visible = module._visible_dataset_files(datadir, files)

    assert visible == [datadir / "visible.csv", Path("/elsewhere/outside.json")]


def test_view_maps_repo_path_helpers(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_module()
    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    apps_root = src_root / "agilab" / "apps"
    apps_root.mkdir(parents=True)
    (apps_root / ".hidden_project").mkdir()
    (apps_root / "notes").mkdir()
    expected_app = apps_root / "alpha_project"
    expected_app.mkdir()
    module_path = src_root / "agilab" / "apps-pages" / "view_maps" / "src" / "view_maps" / "view_maps.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(module.sys, "path", [])

    module._ensure_repo_on_path()

    assert str(src_root) in module.sys.path
    assert str(repo_root) in module.sys.path
    assert module._default_app() == expected_app


def test_view_maps_computes_viewport_for_numeric_coordinates() -> None:
    module = _load_view_maps_module()
    df = pd.DataFrame(
        {
            "lat": ["48.0", "49.0", "bad"],
            "lon": [2.0, 2.8, None],
        }
    )

    viewport = module._compute_viewport(df, "lat", "lon")

    assert viewport == {
        "center_lat": 48.5,
        "center_lon": 2.4,
        "default_zoom": 9,
    }


def test_view_maps_persists_view_settings(tmp_path) -> None:
    module = _load_view_maps_module()
    settings_path = tmp_path / "app_settings.toml"
    env = SimpleNamespace(app_settings_file=settings_path)

    payload = module._persist_view_maps_settings(
        env,
        {"ui": {"map": {"center_lat": 0.0}}},
        {"datadir": "/tmp/export", "file_ext_choice": "csv"},
    )

    assert payload["ui"]["map"]["center_lat"] == 0.0
    assert payload["view_maps"]["datadir"] == "/tmp/export"
    written = settings_path.read_text(encoding="utf-8")
    assert "view_maps" in written
    assert "datadir = \"/tmp/export\"" in written


def test_view_maps_continuous_and_discrete_helpers_set_session_state(monkeypatch) -> None:
    module = _load_view_maps_module()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)

    module.continuous()
    assert fake_st.session_state["coltype"] == "continuous"

    module.discrete()
    assert fake_st.session_state["coltype"] == "discrete"


def test_view_maps_downsample_deterministic_raises_for_non_positive_ratio() -> None:
    module = _load_view_maps_module()
    df = pd.DataFrame({"value": [10, 20, 30]})

    with pytest.raises(ValueError, match="positive integer"):
        module.downsample_df_deterministic(df, 0)


def test_view_maps_downsample_deterministic_samples_every_nth_row() -> None:
    module = _load_view_maps_module()
    df = pd.DataFrame({"value": [10, 20, 30, 40]}, index=[9, 8, 7, 6])

    sampled = module.downsample_df_deterministic(df, 2)

    assert sampled["value"].tolist() == [10, 30]
    assert sampled.index.tolist() == [0, 1]


@pytest.mark.parametrize(
    ("span", "expected"),
    [
        (200.0, 1),
        (81.0, 2),
        (0.0, 15),
    ],
)
def test_view_maps_compute_zoom_from_span(span: float, expected: int) -> None:
    module = _load_view_maps_module()

    assert module._compute_zoom_from_span(span) == expected


def test_view_maps_compute_viewport_returns_none_for_invalid_coordinates() -> None:
    module = _load_view_maps_module()

    assert module._compute_viewport(pd.DataFrame({"lat": ["a"], "lon": ["b"]}), "lat", "lon") is None
    assert module._compute_viewport(pd.DataFrame({"lat": [None], "lon": [None]}), "lat", "lon") is None

    class _BrokenFrame:
        def __getitem__(self, key):
            raise RuntimeError("broken")

    assert module._compute_viewport(_BrokenFrame(), "lat", "lon") is None


def test_view_maps_load_map_defaults_reads_file_and_missing_file(tmp_path) -> None:
    module = _load_view_maps_module()
    missing_env = SimpleNamespace(app_settings_file=tmp_path / "missing.toml")

    assert module._load_map_defaults(missing_env) == {
        "center_lat": 0.0,
        "center_lon": 0.0,
        "default_zoom": 2.5,
    }

    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        "[ui.map]\n"
        "center_lat = 48.85\n"
        "center_lon = 2.35\n"
        "default_zoom = 7.0\n",
        encoding="utf-8",
    )
    env = SimpleNamespace(app_settings_file=settings_path)

    assert module._load_map_defaults(env) == {
        "center_lat": 48.85,
        "center_lon": 2.35,
        "default_zoom": 7.0,
    }


def test_view_maps_load_view_maps_settings_handles_missing_and_non_dict_section(tmp_path) -> None:
    module = _load_view_maps_module()
    missing_env = SimpleNamespace(app_settings_file=tmp_path / "missing.toml")

    data, view = module._load_view_maps_settings(missing_env)
    assert data == {}
    assert view == {}

    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text('view_maps = "unexpected"\n', encoding="utf-8")
    env = SimpleNamespace(app_settings_file=settings_path)

    data, view = module._load_view_maps_settings(env)
    assert data["view_maps"] == "unexpected"
    assert view == {}


def test_view_maps_load_view_maps_settings_handles_invalid_toml(tmp_path) -> None:
    module = _load_view_maps_module()
    settings_path = tmp_path / "broken.toml"
    settings_path.write_text("not = [valid", encoding="utf-8")
    env = SimpleNamespace(app_settings_file=settings_path)

    data, view = module._load_view_maps_settings(env)

    assert data == {}
    assert view == {}


def test_view_maps_persist_view_maps_settings_accepts_non_dict_base(tmp_path) -> None:
    module = _load_view_maps_module()
    settings_path = tmp_path / "app_settings.toml"
    env = SimpleNamespace(app_settings_file=settings_path)

    payload = module._persist_view_maps_settings(env, None, {"datadir": "/tmp/export"})

    assert payload == {"view_maps": {"datadir": "/tmp/export"}}
    assert "view_maps" in settings_path.read_text(encoding="utf-8")


def test_view_maps_persist_view_maps_settings_tolerates_write_failure(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    env = SimpleNamespace(app_settings_file=tmp_path / "missing" / "app_settings.toml")
    monkeypatch.setattr(module, "_dump_toml_payload", lambda data, handle: (_ for _ in ()).throw(RuntimeError("boom")))

    payload = module._persist_view_maps_settings(env, {"ui": {}}, {"datadir": "/tmp/export"})

    assert payload["view_maps"]["datadir"] == "/tmp/export"
    assert not env.app_settings_file.exists()


def test_view_maps_main_rejects_missing_active_app(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    fake_st = _FakeStreamlit()
    monkeypatch.setattr(module, "st", fake_st)
    argv = [Path(PAGE_PATH).name, "--active-app", str(tmp_path / "missing")]

    with patch.object(sys, "argv", argv):
        with pytest.raises(SystemExit) as excinfo:
            module.main()

    assert excinfo.value.code == 1
    assert any("provided --active-app path not found" in message for message in fake_st.calls["error"])


def test_view_maps_main_initializes_env_and_invokes_page(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    fake_st = _FakeStreamlit()
    fake_st.session_state = _State()
    active_app = tmp_path / "src" / "agilab" / "apps" / "builtin" / "demo_project"
    active_app.mkdir(parents=True)
    calls: list[SimpleNamespace] = []

    def fake_agi_env(**kwargs):
        env = SimpleNamespace(
            apps_path=kwargs["apps_path"],
            app=kwargs["app"],
            verbose=kwargs["verbose"],
            target="demo_map",
            AGILAB_EXPORT_ABS=str(tmp_path / "export"),
            app_settings_file=tmp_path / "app_settings.toml",
            TABLE_MAX_ROWS=12,
            GUI_SAMPLING=3,
            is_source_env=True,
            is_worker_env=False,
            projects=["demo_map_project"],
            init_done=False,
        )
        return env

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "AgiEnv", fake_agi_env)
    monkeypatch.setattr(module, "page", lambda env: calls.append(env))

    argv = [Path(PAGE_PATH).name, "--active-app", str(active_app)]
    with patch.object(sys, "argv", argv):
        module.main()

    assert calls and calls[0].app == active_app.name
    assert fake_st.session_state["apps_path"] == str(active_app.parent)
    assert fake_st.session_state["app"] == active_app.name
    assert fake_st.session_state["IS_SOURCE_ENV"] is True
    assert fake_st.session_state["IS_WORKER_ENV"] is False
    assert fake_st.session_state["TABLE_MAX_ROWS"] == 12
    assert fake_st.session_state["GUI_SAMPLING"] == 3
    assert fake_st.calls["info"]


def test_view_maps_page_single_file_mode_renders_overlay_and_caption(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    datadir = tmp_path / "export" / "demo_map"
    datadir.mkdir(parents=True)
    (datadir / "export.csv").write_text(
        "lat,long,beam,alt_m,sat,sat_track_lat,sat_track_long,category,cont_val,int_small,int_large,timestamp\n"
        "48.8566,2.3522,A,1200,SAT1,48.8570,2.3600,x,1.5,1,100,2025-01-01 00:00:00\n",
        encoding="utf-8",
    )
    settings_path = tmp_path / "demo_map_project" / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "[view_maps]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'file_ext_choice = "bogus"\n'
        'df_select_mode = "bogus"\n'
        'df_file = "export.csv"\n'
        'df_files_selected = ["export.csv"]\n'
        'df_file_regex = ""\n'
        'coltype = "discrete"\n'
        'lat = "lat"\n'
        'long = "long"\n'
        'show_sat_overlay = false\n'
        'unique_threshold = 10\n'
        'range_threshold = 200\n',
        encoding="utf-8",
    )
    env = _make_env(tmp_path, datadir)
    env.app_settings_file = settings_path
    fake_st = _FakeStreamlit(
        {
            ("sidebar.selectbox", "File type"): "all",
            ("sidebar.radio", "Dataset selection"): "Single file",
            ("sidebar.selectbox", "DataFrame"): "export.csv",
            ("column.number_input", "Sampling ratio"): 1,
            ("sidebar.multiselect", "Filter beams"): [],
            ("sidebar.checkbox", "Show satellite overlay"): True,
            ("sidebar.number_input", "Discrete threshold (unique values <)"): 3,
            ("sidebar.number_input", "Integer discrete range (max-min <=)"): 100,
            ("selectbox", "discrete"): "int_small",
            ("selectbox", "continuous"): "timestamp",
            ("selectbox", "lat"): "lat",
            ("selectbox", "long"): "long",
            ("selectbox", "Color Sequence"): "Plotly",
            ("column.number_input", "Select the desired number of points:"): 1,
        }
    )

    def fake_find_files(base, ext):
        if ext == ".csv":
            return [datadir / "export.csv"]
        return []

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "find_files", fake_find_files)
    monkeypatch.setattr(module, "load_df", lambda path, with_index=True, cache_buster=None: pd.read_csv(path))

    module.page(env)

    assert any("Showing all 1 available point" in message for message in fake_st.calls["caption"])
    assert fake_st.calls["plotly_chart"]
    assert fake_st.calls["dataframe"]
    assert fake_st.session_state["df_select_mode"] == "Single file"
    assert fake_st.session_state["df_file"] == "export.csv"
    assert fake_st.session_state["lat"] == "lat"
    assert fake_st.session_state["long"] == "long"
    assert fake_st.session_state["coltype"] == "discrete"
    assert fake_st.session_state["view_maps:df_files_selected"] == ["export.csv"]


def test_view_maps_page_regex_mode_reports_load_errors_and_uses_continuous_color_scale(
    tmp_path, monkeypatch
) -> None:
    module = _load_view_maps_module()
    datadir = tmp_path / "export" / "demo_map"
    datadir.mkdir(parents=True)
    export_csv = datadir / "export.csv"
    other_csv = datadir / "other.csv"
    export_csv.write_text(
        "lat,long,beam,alt_m,sat,sat_track_lat,sat_track_long,category,cont_val,int_small,int_large,timestamp\n"
        "48.8566,2.3522,A,1200,SAT1,48.8570,2.3600,x,1.5,1,100,2025-01-01 00:00:00\n"
        "48.8570,2.3600,A,1210,SAT1,48.8580,2.3610,x,2.5,2,200,2025-01-02 00:00:00\n"
        "48.8580,2.3610,B,1220,SAT2,48.8590,2.3620,y,3.5,1,300,2025-01-03 00:00:00\n"
        "48.8590,2.3620,B,1230,SAT2,48.8600,2.3630,y,4.5,2,400,2025-01-04 00:00:00\n"
        "48.8600,2.3630,C,1240,SAT3,48.8610,2.3640,z,5.5,1,500,2025-01-05 00:00:00\n"
        "48.8610,2.3640,C,1250,SAT3,48.8620,2.3650,z,6.5,2,600,2025-01-06 00:00:00\n",
        encoding="utf-8",
    )
    other_csv.write_text(export_csv.read_text(encoding="utf-8"), encoding="utf-8")
    settings_path = tmp_path / "demo_map_project" / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "[view_maps]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'file_ext_choice = "all"\n'
        'df_select_mode = "Regex (multi)"\n'
        'df_file_regex = ".*\\\\.csv$"\n'
        'coltype = "continuous"\n'
        'lat = "lat"\n'
        'long = "long"\n'
        'show_sat_overlay = true\n'
        'unique_threshold = 10\n'
        'range_threshold = 200\n',
        encoding="utf-8",
    )
    env = _make_env(tmp_path, datadir)
    env.app_settings_file = settings_path
    fake_st = _FakeStreamlit(
        {
            ("sidebar.selectbox", "File type"): "all",
            ("sidebar.radio", "Dataset selection"): "Regex (multi)",
            ("sidebar.text_input", "DataFrame filename regex"): ".*\\.csv$",
            ("sidebar.button", "Select all matching (2)"): True,
            ("sidebar.multiselect", "DataFrames"): ["export.csv", "other.csv"],
            ("column.number_input", "Sampling ratio"): 2,
            ("sidebar.multiselect", "Filter beams"): ["A"],
            ("sidebar.checkbox", "Show satellite overlay"): False,
            ("sidebar.number_input", "Discrete threshold (unique values <)"): 3,
            ("sidebar.number_input", "Integer discrete range (max-min <=)"): 100,
            ("selectbox", "discrete"): "beam",
            ("selectbox", "continuous"): "cont_val",
            ("selectbox", "lat"): "lat",
            ("selectbox", "long"): "long",
            ("slider", "Select the desired number of points:"): 3,
        }
    )

    def fake_find_files(base, ext):
        if ext == ".csv":
            return [export_csv, other_csv]
        return []

    def fake_load_df(path, with_index=True, cache_buster=None):
        if path.name == "other.csv":
            raise ValueError("broken dataset")
        return pd.read_csv(path)

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "find_files", fake_find_files)
    monkeypatch.setattr(module, "load_df", fake_load_df)

    module.page(env)

    assert any("Some selected files failed to load" in message for message in fake_st.calls["sidebar.warning"])
    assert any("broken dataset" in message for message in fake_st.calls["write"])
    assert fake_st.calls["plotly_chart"]
    assert fake_st.session_state["df_select_mode"] == "Regex (multi)"
    assert fake_st.session_state["coltype"] == "continuous"
    assert fake_st.session_state["df_files_selected"] == ["export.csv", "other.csv"]
    assert fake_st.session_state["view_maps:df_files_selected"] == ["export.csv", "other.csv"]
    assert fake_st.session_state["df_file"] == "export.csv"


def test_view_maps_page_reports_discovery_errors_as_no_dataset(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    datadir = tmp_path / "export" / "demo_map"
    datadir.mkdir(parents=True)
    settings_path = tmp_path / "demo_map_project" / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "[view_maps]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'file_ext_choice = "all"\n'
        'df_select_mode = "Single file"\n',
        encoding="utf-8",
    )
    env = _make_env(tmp_path, datadir)
    env.app_settings_file = settings_path
    fake_st = _FakeStreamlit()

    def fake_find_files(base, ext):
        raise NotADirectoryError("not a directory")

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "find_files", fake_find_files)

    with pytest.raises(_StopExecution):
        module.page(env)

    assert any("not a directory" in message for message in fake_st.calls["warning"])
    assert any("No dataset found" in message for message in fake_st.calls["warning"])


def test_view_maps_page_reports_invalid_regex_and_falls_back_to_default_selection(
    tmp_path, monkeypatch
) -> None:
    module = _load_view_maps_module()
    datadir = tmp_path / "export" / "demo_map"
    datadir.mkdir(parents=True)
    (datadir / "export.csv").write_text(
        "lat,long,beam,alt_m,cont_val,timestamp\n"
        "48.8566,2.3522,A,1200,1.5,2025-01-01 00:00:00\n",
        encoding="utf-8",
    )
    settings_path = tmp_path / "demo_map_project" / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "[view_maps]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'file_ext_choice = "all"\n'
        'df_select_mode = "Regex (multi)"\n'
        'df_file = "export.csv"\n'
        'df_files_selected = ["export.csv"]\n'
        'coltype = "discrete"\n'
        'lat = "lat"\n'
        'long = "long"\n',
        encoding="utf-8",
    )
    env = _make_env(tmp_path, datadir)
    env.app_settings_file = settings_path
    fake_st = _FakeStreamlit(
        {
            ("sidebar.selectbox", "File type"): "all",
            ("sidebar.radio", "Dataset selection"): "Regex (multi)",
            ("sidebar.text_input", "DataFrame filename regex"): "(",
            ("sidebar.multiselect", "DataFrames"): ["export.csv"],
            ("column.number_input", "Sampling ratio"): 1,
            ("sidebar.multiselect", "Filter beams"): [],
            ("sidebar.checkbox", "Show satellite overlay"): False,
            ("sidebar.number_input", "Discrete threshold (unique values <)"): 3,
            ("sidebar.number_input", "Integer discrete range (max-min <=)"): 100,
            ("selectbox", "discrete"): "beam",
            ("selectbox", "continuous"): "cont_val",
            ("selectbox", "lat"): "lat",
            ("selectbox", "long"): "long",
            ("selectbox", "Color Sequence"): "Plotly",
            ("slider", "Select the desired number of points:"): 1,
        }
    )

    def fake_find_files(base, ext):
        if ext == ".csv":
            return [datadir / "export.csv"]
        return []

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "find_files", fake_find_files)
    monkeypatch.setattr(module, "load_df", lambda path, with_index=True, cache_buster=None: pd.read_csv(path))

    module.page(env)

    assert any("Invalid regex" in message for message in fake_st.calls["sidebar.error"])
    assert fake_st.calls["plotly_chart"]


def test_view_maps_page_warns_for_missing_directory(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    datadir = tmp_path / "missing-dir"
    settings_path = tmp_path / "demo_map_project" / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "[view_maps]\n"
        f'datadir = "{datadir.as_posix()}"\n',
        encoding="utf-8",
    )
    env = _make_env(tmp_path, datadir)
    env.app_settings_file = settings_path
    fake_st = _FakeStreamlit()

    monkeypatch.setattr(module, "st", fake_st)

    module.page(env)

    assert any("Directory not found." in message for message in fake_st.calls["sidebar.error"])
    assert any("A valid data directory is required to proceed." in message for message in fake_st.calls["warning"])


def test_view_maps_page_warns_when_no_dataset_is_selected(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    datadir = tmp_path / "export" / "demo_map"
    datadir.mkdir(parents=True)
    (datadir / "export.csv").write_text("lat,long\n48.0,2.0\n", encoding="utf-8")
    settings_path = tmp_path / "demo_map_project" / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "[view_maps]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'df_select_mode = "Multi-select"\n',
        encoding="utf-8",
    )
    env = _make_env(tmp_path, datadir)
    env.app_settings_file = settings_path
    fake_st = _FakeStreamlit(
        {
            ("sidebar.selectbox", "File type"): "all",
            ("sidebar.radio", "Dataset selection"): "Multi-select",
            ("sidebar.multiselect", "DataFrames"): [],
        }
    )

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "find_files", lambda base, ext: [datadir / "export.csv"] if ext == ".csv" else [])

    module.page(env)

    assert any("Please select at least one dataset to proceed." in message for message in fake_st.calls["warning"])


def test_view_maps_page_reports_invalid_loaded_data_and_concat_failure(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    datadir = tmp_path / "export" / "demo_map"
    datadir.mkdir(parents=True)
    export_csv = datadir / "export.csv"
    export_csv.write_text("lat,long\n48.0,2.0\n", encoding="utf-8")
    settings_path = tmp_path / "demo_map_project" / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "[view_maps]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'df_select_mode = "Single file"\n'
        'df_file = "export.csv"\n'
        'df_files_selected = ["export.csv"]\n',
        encoding="utf-8",
    )
    env = _make_env(tmp_path, datadir)
    env.app_settings_file = settings_path

    fake_st = _FakeStreamlit(
        {
            ("sidebar.selectbox", "File type"): "all",
            ("sidebar.radio", "Dataset selection"): "Single file",
            ("sidebar.selectbox", "DataFrame"): "export.csv",
        }
    )
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "find_files", lambda base, ext: [export_csv] if ext == ".csv" else [])
    monkeypatch.setattr(module, "load_df", lambda path, with_index=True, cache_buster=None: "not-a-dataframe")

    module.page(env)

    assert any("No selected dataframes could be loaded." in message for message in fake_st.calls["error"])

    fake_st = _FakeStreamlit(
        {
            ("sidebar.selectbox", "File type"): "all",
            ("sidebar.radio", "Dataset selection"): "Single file",
            ("sidebar.selectbox", "DataFrame"): "export.csv",
        }
    )
    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "load_df", lambda path, with_index=True, cache_buster=None: pd.DataFrame({"lat": [1.0], "long": [2.0]}))
    monkeypatch.setattr(module.pd, "concat", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("cannot concat")))

    module.page(env)

    assert any("Error concatenating datasets: cannot concat" in message for message in fake_st.calls["error"])


def test_view_maps_page_warns_without_lat_lon_columns(tmp_path, monkeypatch) -> None:
    module = _load_view_maps_module()
    datadir = tmp_path / "export" / "demo_map"
    datadir.mkdir(parents=True)
    export_csv = datadir / "export.csv"
    export_csv.write_text("beam,category\nA,x\nB,y\n", encoding="utf-8")
    settings_path = tmp_path / "demo_map_project" / "src" / "app_settings.toml"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        "[view_maps]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'df_select_mode = "Single file"\n'
        'df_file = "export.csv"\n'
        'df_files_selected = ["export.csv"]\n',
        encoding="utf-8",
    )
    env = _make_env(tmp_path, datadir)
    env.app_settings_file = settings_path
    fake_st = _FakeStreamlit(
        {
            ("sidebar.selectbox", "File type"): "all",
            ("sidebar.radio", "Dataset selection"): "Single file",
            ("sidebar.selectbox", "DataFrame"): "export.csv",
            ("column.number_input", "Sampling ratio"): 1,
            ("sidebar.checkbox", "Show satellite overlay"): False,
            ("sidebar.number_input", "Discrete threshold (unique values <)"): 3,
            ("sidebar.number_input", "Integer discrete range (max-min <=)"): 100,
        }
    )

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "find_files", lambda base, ext: [export_csv] if ext == ".csv" else [])
    monkeypatch.setattr(module, "load_df", lambda path, with_index=True, cache_buster=None: pd.read_csv(path))

    module.page(env)

    assert any("Latitude and Longitude columns are required for the map." in message for message in fake_st.calls["warning"])
