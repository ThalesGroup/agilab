from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import warnings

import pandas as pd
import pytest

PAGE_PATH = "src/agilab/apps-pages/view_maps_3d/src/view_maps_3d/view_maps_3d.py"
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
        default = value if value is not None else kwargs.get("min_value")
        return self._streamlit._widget_value("column.number_input", label, key=key, default=default)


class _FakeSidebar(_NullContext):
    def __init__(self, streamlit):
        self._streamlit = streamlit

    def text_input(self, label, *args, key=None, value="", **kwargs):
        default = value if key is None else self._streamlit.session_state.get(key, value)
        return self._streamlit._widget_value("sidebar.text_input", label, key=key, default=default)

    def selectbox(self, label, options, *args, key=None, index=0, **kwargs):
        default = (
            self._streamlit.session_state.get(key)
            if key is not None and key in self._streamlit.session_state
            else (options[index] if options and index is not None else None)
        )
        return self._streamlit._widget_value("sidebar.selectbox", label, key=key, default=default, options=options)

    def radio(self, label, options, *args, key=None, index=0, **kwargs):
        default = (
            self._streamlit.session_state.get(key)
            if key is not None and key in self._streamlit.session_state
            else (options[index] if options and index is not None else None)
        )
        return self._streamlit._widget_value("sidebar.radio", label, key=key, default=default, options=options)

    def multiselect(self, label, options, *args, key=None, default=None, **kwargs):
        default = list(default or self._streamlit.session_state.get(key, []))
        return self._streamlit._widget_value("sidebar.multiselect", label, key=key, default=default, options=options)

    def button(self, label, *args, key=None, disabled=False, **kwargs):
        return self._streamlit._widget_value("sidebar.button", label, key=key, default=False)

    def file_uploader(self, label, *args, **kwargs):
        return self._streamlit._widget_value("sidebar.file_uploader", label, default=None)

    def download_button(self, label, *args, **kwargs):
        self._streamlit.calls["sidebar.download_button"].append(label)

    def expander(self, label, *args, **kwargs):
        self._streamlit.calls["sidebar.expander"].append(label)
        return _NullContext()

    def caption(self, message):
        self._streamlit.calls["sidebar.caption"].append(message)

    def error(self, message):
        self._streamlit.calls["sidebar.error"].append(message)

    def warning(self, message):
        self._streamlit.calls["sidebar.warning"].append(message)

    def success(self, message):
        self._streamlit.calls["sidebar.success"].append(message)

    def markdown(self, message, *args, **kwargs):
        self._streamlit.calls["sidebar.markdown"].append(message)


class _FakeStreamlit:
    def __init__(self, widget_values: dict | None = None):
        self.session_state = _State({"GUI_SAMPLING": 1, "TABLE_MAX_ROWS": 10})
        self.sidebar = _FakeSidebar(self)
        self.widget_values = widget_values or {}
        self.calls = {
            "warning": [],
            "error": [],
            "info": [],
            "markdown": [],
            "write": [],
            "pydeck_chart": [],
            "sidebar.caption": [],
            "sidebar.error": [],
            "sidebar.warning": [],
            "sidebar.success": [],
            "sidebar.markdown": [],
            "sidebar.download_button": [],
            "sidebar.expander": [],
            "code": [],
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

    def selectbox(self, label, options, *args, key=None, index=0, **kwargs):
        default = (
            self.session_state.get(key)
            if key is not None and key in self.session_state
            else (options[index] if options and index is not None else None)
        )
        return self._widget_value("selectbox", label, key=key, default=default, options=options)

    def slider(self, label, *args, key=None, value=None, **kwargs):
        default = value if value is not None else kwargs.get("min_value")
        return self._widget_value("slider", label, key=key, default=default)

    def multiselect(self, label, options, *args, key=None, default=None, **kwargs):
        default = list(default or self.session_state.get(key, []))
        return self._widget_value("multiselect", label, key=key, default=default, options=options)

    def text_input(self, label, *args, key=None, value="", **kwargs):
        default = value if key is None else self.session_state.get(key, value)
        return self._widget_value("text_input", label, key=key, default=default)

    def columns(self, count):
        return [_FakeColumn(self) for _ in range(count)]

    def markdown(self, message, *args, **kwargs):
        self.calls["markdown"].append(message)

    def write(self, *args, **kwargs):
        self.calls["write"].append(" ".join(str(arg) for arg in args))

    def pydeck_chart(self, *args, **kwargs):
        self.calls["pydeck_chart"].append((args, kwargs))

    def info(self, message, *args, **kwargs):
        self.calls["info"].append(message)

    def warning(self, message, *args, **kwargs):
        self.calls["warning"].append(message)

    def error(self, message, *args, **kwargs):
        self.calls["error"].append(message)

    def code(self, message, *args, **kwargs):
        self.calls["code"].append(message)

    def stop(self):
        raise _StopExecution()


def _load_view_maps_3d_module():
    spec = importlib.util.spec_from_file_location("view_maps_3d_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with warnings.catch_warnings():
        _suppress_page_import_warnings()
        with patch("streamlit.title", lambda *args, **kwargs: None):
            spec.loader.exec_module(module)
    return module


def test_view_maps_3d_warns_when_no_dataset_exists(tmp_path, create_temp_app_project, run_page_app_test) -> None:
    missing_export_root = tmp_path / "export"
    beam_dir = tmp_path / "beams"
    project_dir = create_temp_app_project(
        "demo_map_3d_project",
        "demo_map_3d",
        "[view_maps_3d]\n"
        f"datadir = \"{(missing_export_root / 'demo_map_3d').as_posix()}\"\n"
        f"beamdir = \"{beam_dir.as_posix()}\"\n"
        "file_ext_choice = \"all\"\n"
        "df_select_mode = \"Single file\"\n",
        pyproject_name="demo-map-3d-project",
    )
    at = run_page_app_test(PAGE_PATH, project_dir, export_root=missing_export_root)

    assert not at.exception
    assert any("Cartography-3D Visualisation" in title.value for title in at.title)
    assert any("No dataset found" in warning.value for warning in at.warning)
    assert any(widget.label == "Data Directory" for widget in at.text_input)


def test_view_maps_3d_lists_dataset_files_sorted_without_duplicates(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    datadir = tmp_path / "datasets"

    a = datadir / "b.csv"
    b = datadir / "a.csv"
    monkeypatch.setattr(module, "find_files", lambda base, ext: [a, b, a] if ext == ".csv" else [])

    listed = module._list_dataset_files(datadir, "csv")

    assert listed == [b, a]


def test_view_maps_3d_repo_path_helpers(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    apps_root = src_root / "agilab" / "apps"
    apps_root.mkdir(parents=True)
    (apps_root / ".hidden_project").mkdir()
    (apps_root / "notes").mkdir()
    expected_app = apps_root / "alpha_project"
    expected_app.mkdir()
    module_path = src_root / "agilab" / "apps-pages" / "view_maps_3d" / "src" / "view_maps_3d" / "view_maps_3d.py"
    module_path.parent.mkdir(parents=True)
    module_path.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(module.sys, "path", [])

    module._ensure_repo_on_path()

    assert str(src_root) in module.sys.path
    assert str(repo_root) in module.sys.path
    assert module._default_app() == expected_app


def test_view_maps_3d_initializes_visible_dataset_files(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    datadir = tmp_path / "datasets"
    visible = datadir / "visible.csv"
    hidden = datadir / ".shadow" / "ignored.csv"

    monkeypatch.setattr(module, "_list_dataset_files", lambda base_dir, ext_choice="all": [visible, hidden])
    state = _State(datadir=datadir)
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))

    module.initialize_csv_files()

    assert state["dataset_files"] == [visible]
    assert state["csv_files"] == [visible]
    assert state["df_file"] == "visible.csv"


def test_view_maps_3d_initializes_visible_beam_files(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    beamdir = tmp_path / "beams"
    visible = beamdir / "beam.csv"
    hidden = beamdir / ".shadow" / "ignored.csv"

    monkeypatch.setattr(module, "find_files", lambda base: [visible, hidden])
    state = _State(beamdir=beamdir)
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))

    module.initialize_beam_files()

    assert state["beam_csv_files"] == [visible]
    assert state["beam_file"] == "beam.csv"


def test_view_maps_3d_converts_hex_and_geojson_helpers() -> None:
    module = _load_view_maps_3d_module()
    geojson_data = {
        "features": [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[2.0, 48.0], [2.1, 48.0], [2.0, 48.1], [2.0, 48.0]]],
                }
            },
            {
                "geometry": {
                    "type": "MultiPolygon",
                    "coordinates": [
                        [[[3.0, 47.0], [3.1, 47.0], [3.0, 47.1], [3.0, 47.0]]],
                    ],
                }
            },
        ]
    }

    assert module.hex_to_rgb("#A1B2C3") == (161, 178, 195)
    assert module.hex_to_rgb("oops") == (0, 0, 0)

    df = module.poly_geojson_to_csv(geojson_data)

    assert list(df.columns) == ["polygon_index", "longitude", "latitude"]
    assert len(df) == 8
    assert set(df["polygon_index"]) == {0, 1}


def test_view_maps_3d_get_palette_and_update_beamdir(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    messages: list[str] = []
    monkeypatch.setattr(module.st, "error", lambda message: messages.append(message))

    assert module.get_palette("Plotly")
    assert module.get_palette("NoSuchPalette") == []
    assert messages and "Palette 'NoSuchPalette' not found." in messages[-1]

    state = _State(
        beamdir="old",
        beam_file="old.csv",
        beam_csv_files=["old.csv"],
        input_beamdir=str(tmp_path / "new_beams"),
    )
    calls: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))
    monkeypatch.setattr(module, "initialize_beam_files", lambda: calls.append("called"))

    module.update_beamdir("beamdir", "input_beamdir")

    assert "beam_file" not in state
    assert "beam_csv_files" not in state
    assert state["beamdir"] == str(tmp_path / "new_beams")
    assert calls == ["called"]


def test_view_maps_3d_update_datadir_clears_cached_dataset_state(monkeypatch) -> None:
    module = _load_view_maps_3d_module()
    session_state = {
        "df_file": "old.csv",
        "df_files_selected": ["old.csv"],
        "csv_files": ["old.csv"],
        "dataset_files": [Path("old.csv")],
        "loaded_df": pd.DataFrame({"lat": [1.0]}),
        "input_datadir": "/tmp/new-datadir",
    }
    initialize_calls: list[str] = []

    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))
    monkeypatch.setattr(module, "initialize_csv_files", lambda: initialize_calls.append("called"))

    module.update_datadir("datadir", "input_datadir")

    for key in ("df_file", "df_files_selected", "csv_files", "dataset_files", "loaded_df"):
        assert key not in session_state
    assert session_state["datadir"] == "/tmp/new-datadir"
    assert initialize_calls == ["called"]


def test_view_maps_3d_generates_palette_maps_and_basic_state_updates(monkeypatch) -> None:
    module = _load_view_maps_3d_module()

    randint_values = iter([101, 102, 103, 104, 105, 106])
    monkeypatch.setattr(module.random, "randint", lambda low, high: next(randint_values))
    assert module.generate_random_colors(2) == [[101, 102, 103], [104, 105, 106]]

    color_map = module.get_category_color_map(
        pd.DataFrame({"kind": ["A", "B", "C"]}),
        "kind",
        "Plotly",
    )
    assert set(color_map) == {"A", "B", "C"}
    assert all(len(rgb) == 3 for rgb in color_map.values())

    state = _State(input_value="fresh")
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))
    module.update_var("saved_value", "input_value")
    module.continious()
    assert state["saved_value"] == "fresh"
    assert state["coltype"] == "continious"
    module.discrete()
    assert state["coltype"] == "discrete"
    assert module._vm3d_key("dataset") == "view_maps_3d:dataset"


def test_view_maps_3d_category_color_map_repeats_short_palettes(monkeypatch) -> None:
    module = _load_view_maps_3d_module()
    monkeypatch.setattr(module, "get_palette", lambda _name: ["#010203"])

    color_map = module.get_category_color_map(
        pd.DataFrame({"kind": ["A", "B", "C"]}),
        "kind",
        "single",
    )

    assert color_map == {
        "A": (1, 2, 3),
        "B": (1, 2, 3),
        "C": (1, 2, 3),
    }


def test_view_maps_3d_moves_data_and_downsamples_deterministically(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()

    messages: list[str] = []
    update_calls: list[tuple[str, str]] = []
    beamdir = tmp_path / "beamdir"
    beamdir.mkdir()
    state = _State(beamdir=str(beamdir))
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(session_state=state, sidebar=SimpleNamespace(success=messages.append)),
    )
    monkeypatch.setattr(module, "update_beamdir", lambda var_key, widget_key: update_calls.append((var_key, widget_key)))

    module.move_to_data("beam.csv", "a,b\n1,2\n")

    written = (beamdir / "beam.csv").read_text(encoding="utf-8")
    assert written == "a,b\n1,2\n"
    assert messages == [f"File moved to {beamdir / 'beam.csv'}"]
    assert update_calls == [("beamdir", "input_beamdir")]

    df = pd.DataFrame({"value": [10, 20, 30, 40]}, index=[9, 8, 7, 6])
    downsampled = module.downsample_df_deterministic(df, 2)
    assert downsampled.to_dict("records") == [{"value": 10}, {"value": 30}]
    with pytest.raises(ValueError, match="positive integer"):
        module.downsample_df_deterministic(df, 0)


def test_view_maps_3d_lists_multiple_extensions_and_preserves_existing_dataset_choice(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    datadir = tmp_path / "datasets"
    csv_file = datadir / "b.csv"
    parquet_file = datadir / "a.parquet"
    json_file = datadir / "c.json"

    def fake_find_files(base, ext=None):
        mapping = {
            ".csv": [csv_file, csv_file],
            ".parquet": [parquet_file],
            ".json": [json_file],
        }
        return mapping.get(ext, [])

    monkeypatch.setattr(module, "find_files", fake_find_files)
    assert module._list_dataset_files(datadir, "all") == [parquet_file, csv_file, json_file]

    state = _State(datadir=datadir, dataset_files=[csv_file], csv_files=[csv_file], df_file="already.csv")
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=state))
    module.initialize_csv_files()
    assert state["df_file"] == "already.csv"


def test_view_maps_3d_page_requires_env(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    messages: list[str] = []
    stop_calls: list[str] = []

    class _StopCalled(RuntimeError):
        pass

    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state={},
            error=messages.append,
            stop=lambda: (stop_calls.append("stop"), (_ for _ in ()).throw(_StopCalled()))[1],
        ),
    )

    with pytest.raises(_StopCalled):
        module.page()

    assert any("not initialized" in message for message in messages)
    assert stop_calls == ["stop"]


def test_view_maps_3d_page_rejects_invalid_datadir(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    settings_file = tmp_path / "app_settings.toml"
    settings_file.write_text("", encoding="utf-8")
    fake_st = _FakeStreamlit()
    invalid_path = tmp_path / "not_a_directory"
    invalid_path.write_text("x", encoding="utf-8")
    fake_st.session_state["env"] = SimpleNamespace(
        app_settings_file=settings_file,
        AGILAB_EXPORT_ABS=tmp_path / "export",
        target="demo_map_3d_project",
        projects=["demo_map_3d_project"],
        share_root_path=lambda: tmp_path / "share",
    )
    fake_st.session_state["datadir"] = invalid_path
    fake_st.session_state["beamdir"] = tmp_path / "beams"

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "render_logo", lambda *_args, **_kwargs: None)

    module.page()

    assert fake_st.calls["sidebar.error"] == ["Directory not found."]
    assert any("valid data directory" in message for message in fake_st.calls["warning"])


def test_view_maps_3d_page_handles_invalid_regex_and_empty_selection(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    datadir = tmp_path / "datasets"
    datadir.mkdir()
    settings_file = tmp_path / "app_settings.toml"
    settings_file.write_text(
        "[view_maps_3d]\n"
        'file_ext_choice = "txt"\n'
        'df_select_mode = "invalid-mode"\n',
        encoding="utf-8",
    )
    selection_key = module._vm3d_key("df_files_selected")
    fake_st = _FakeStreamlit(
        widget_values={
            ("sidebar.radio", "Dataset selection"): "Regex (multi)",
            ("sidebar.text_input", "DataFrame filename regex"): "[",
            ("sidebar.multiselect", selection_key): [],
        }
    )
    fake_st.session_state["env"] = SimpleNamespace(
        app_settings_file=settings_file,
        AGILAB_EXPORT_ABS=tmp_path / "export",
        target="demo_map_3d_project",
        projects=["demo_map_3d_project"],
        share_root_path=lambda: tmp_path / "share",
    )

    visible_file = datadir / "ok.csv"
    hidden_file = datadir / ".hidden" / "skip.csv"
    outside_file = tmp_path / "outside.csv"

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "render_logo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "_list_dataset_files",
        lambda *_args, **_kwargs: [visible_file, hidden_file, outside_file],
    )

    module.page()

    assert fake_st.session_state["file_ext_choice"] == "all"
    assert any("Invalid regex" in message for message in fake_st.calls["sidebar.error"])
    assert any("0 / 0 files match" in message for message in fake_st.calls["sidebar.caption"])
    assert any("Please select at least one dataset" in message for message in fake_st.calls["warning"])


def test_view_maps_3d_page_renders_loaded_datasets_and_geojson_controls(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    datadir = tmp_path / "datasets"
    beamdir = tmp_path / "beams"
    datadir.mkdir()
    beamdir.mkdir()
    settings_file = tmp_path / "app_settings.toml"
    settings_file.write_text(
        "[view_maps_3d]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        f'beamdir = "{beamdir.as_posix()}"\n',
        encoding="utf-8",
    )
    selection_key = module._vm3d_key("df_files_selected")
    beam_selection_key = module._vm3d_key("beam_files")
    widget_values = {
        ("sidebar.multiselect", selection_key): ["good.csv", "empty.csv", "weird.csv", "broken.csv"],
        ("sidebar.multiselect", beam_selection_key): ["beam.csv"],
        ("sidebar.file_uploader", "Upload your GeoJSON file"): object(),
        ("sidebar.text_input", "Enter the name for your converted CSV file"): "converted.csv",
        ("sidebar.button", "Move to data"): True,
        ("multiselect", "Select Layers"): ["Terrain", "Flight Path", "Beams"],
    }
    fake_st = _FakeStreamlit(widget_values=widget_values)
    line_limit_key = module._vm3d_key("table_max_rows")
    fake_st.session_state["env"] = SimpleNamespace(
        app_settings_file=settings_file,
        AGILAB_EXPORT_ABS=tmp_path / "export",
        target="demo_map_3d_project",
        projects=["demo_map_3d_project"],
        share_root_path=lambda: tmp_path / "share",
    )
    fake_st.session_state[selection_key] = "not-a-list"
    fake_st.session_state[beam_selection_key] = "not-a-list"
    fake_st.session_state["TABLE_MAX_ROWS"] = "not-an-int"
    fake_st.session_state[line_limit_key] = "still-not-an-int"

    good_df = pd.DataFrame(
        {
            "cluster_id": [idx % 2 for idx in range(20)],
            "metric": list(range(20)),
            "lat": [43.0 + idx * 0.01 for idx in range(20)],
            "long": [1.0 + idx * 0.01 for idx in range(20)],
            "alt": [1000 + idx * 10 for idx in range(20)],
        }
    )
    beam_df = pd.DataFrame(
        {
            "polygon_index": [0, 0, 0, 1, 1, 1],
            "longitude": [1.0, 1.1, 1.0, 2.0, 2.1, 2.0],
            "latitude": [43.0, 43.0, 43.1, 44.0, 44.0, 44.1],
        }
    )
    saved_payloads: list[dict] = []
    preview_calls: list[pd.DataFrame] = []
    moved_files: list[tuple[str, str]] = []

    class _FakePdk:
        class Layer:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

        class ViewState:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class Deck:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

    def fake_load_df(path, **_kwargs):
        name = Path(path).name
        if name == "good.csv":
            return good_df.copy()
        if name == "empty.csv":
            return pd.DataFrame()
        if name == "weird.csv":
            return ["unexpected"]
        if name == "broken.csv":
            raise ValueError("boom")
        if name == "beam.csv":
            return beam_df.copy()
        raise AssertionError(f"Unexpected load request: {path}")

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "pdk", _FakePdk)
    monkeypatch.setattr(module, "render_logo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "_list_dataset_files",
        lambda *_args, **_kwargs: [
            datadir / "good.csv",
            datadir / "empty.csv",
            datadir / "weird.csv",
            datadir / "broken.csv",
        ],
    )
    monkeypatch.setattr(
        module,
        "find_files",
        lambda base, recursive=False, ext=None: [beamdir / "beam.csv"] if Path(base) == beamdir else [],
    )
    monkeypatch.setattr(module, "load_df", fake_load_df)
    monkeypatch.setattr(
        module,
        "render_dataframe_preview",
        lambda df, **_kwargs: preview_calls.append(df.copy()),
    )
    monkeypatch.setattr(
        module,
        "_dump_toml_payload",
        lambda payload, fh: (saved_payloads.append(payload), fh.write(b"[view_maps_3d]\n")),
    )
    monkeypatch.setattr(module.geojson, "load", lambda *_args, **_kwargs: {"features": []})
    monkeypatch.setattr(module, "poly_geojson_to_csv", lambda *_args, **_kwargs: pd.DataFrame({"x": [1], "y": [2]}))
    monkeypatch.setattr(module, "move_to_data", lambda name, csv: moved_files.append((name, csv)))

    module.page()

    assert any("Some selected files failed to load" in message for message in fake_st.calls["sidebar.warning"])
    assert fake_st.calls["sidebar.expander"] == ["Load errors"]
    assert any("empty.csv: empty dataframe" in message for message in fake_st.calls["write"])
    assert any("weird.csv: unexpected type" in message for message in fake_st.calls["write"])
    assert any("broken.csv: boom" in message for message in fake_st.calls["write"])
    assert fake_st.calls["sidebar.download_button"] == ["Download CSV"]
    assert moved_files and moved_files[0][0] == "converted.csv"
    assert moved_files[0][1].strip() == "x,y\n1,2"
    assert fake_st.calls["pydeck_chart"]
    assert preview_calls and "__dataset__" in preview_calls[0].columns
    assert fake_st.session_state["beam_files"] == ["beam.csv"]
    assert saved_payloads and saved_payloads[0]["view_maps_3d"]["df_files_selected"] == [
        "good.csv",
        "empty.csv",
        "weird.csv",
        "broken.csv",
    ]
    assert saved_payloads[0]["view_maps_3d"]["beam_files"] == ["beam.csv"]


def test_view_maps_3d_main_reports_missing_active_app(monkeypatch) -> None:
    module = _load_view_maps_3d_module()
    fake_st = _FakeStreamlit()

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module.sys, "argv", ["view_maps_3d.py", "--active-app", "/tmp/does-not-exist"])

    with pytest.raises(SystemExit):
        module.main()

    assert any("provided --active-app path not found" in message for message in fake_st.calls["error"])


def test_view_maps_3d_renders_valid_dataset_without_beams(
    tmp_path, create_temp_app_project, run_page_app_test
) -> None:
    export_root = tmp_path / "export"
    data_dir = export_root / "demo_map_3d"
    data_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "cluster_id": [idx % 2 for idx in range(20)],
            "metric": list(range(20)),
            "lat": [43.0 + idx * 0.01 for idx in range(20)],
            "long": [1.0 + idx * 0.01 for idx in range(20)],
            "alt": [1000 + idx * 10 for idx in range(20)],
        }
    ).to_csv(data_dir / "flight.csv", index=False)
    missing_beam_dir = tmp_path / "missing_beams"
    project_dir = create_temp_app_project(
        "demo_map_3d_project",
        "demo_map_3d",
        "[view_maps_3d]\n"
        f'datadir = "{data_dir.as_posix()}"\n'
        f'beamdir = "{missing_beam_dir.as_posix()}"\n'
        'file_ext_choice = "csv"\n'
        'df_select_mode = "Single file"\n',
        pyproject_name="demo-map-3d-project",
    )

    at = run_page_app_test(PAGE_PATH, project_dir, export_root=export_root)

    assert not at.exception
    assert any("Cartography-3D Visualisation" in title.value for title in at.title)


def test_view_maps_3d_default_app_and_initializer_fallbacks(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()

    fake_module_path = tmp_path / "repo" / "src" / "agilab" / "apps-pages" / "view_maps_3d.py"
    fake_module_path.parent.mkdir(parents=True)
    fake_module_path.write_text("# stub\n", encoding="utf-8")
    monkeypatch.setattr(module, "__file__", str(fake_module_path))

    assert module._default_app() is None

    apps_dir = fake_module_path.parents[4] / "apps"
    apps_dir.mkdir(parents=True, exist_ok=True)
    (apps_dir / "not_an_app").mkdir()
    assert module._default_app() is None

    datadir = tmp_path / "data"
    datadir.mkdir()
    module.st = _FakeStreamlit()
    module.st.session_state.datadir = datadir
    module.st.session_state["df_file"] = "keep.csv"
    outside_dataset = tmp_path / "outside.csv"
    outside_dataset.write_text("x\n1\n", encoding="utf-8")
    monkeypatch.setattr(module, "_list_dataset_files", lambda *_args, **_kwargs: [outside_dataset])
    module.initialize_csv_files()
    assert module.st.session_state["dataset_files"] == [outside_dataset]
    assert module.st.session_state["csv_files"] == [outside_dataset]

    beamdir = tmp_path / "beamdir"
    beamdir.mkdir()
    module.st.session_state.beamdir = beamdir
    module.st.session_state["beam_file"] = "keep_beam.csv"
    outside_beam = tmp_path / "outside_beam.csv"
    outside_beam.write_text("x\n1\n", encoding="utf-8")
    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [outside_beam])
    module.initialize_beam_files()
    assert module.st.session_state["beam_csv_files"] == [outside_beam]


def test_view_maps_3d_page_handles_selection_and_load_fallbacks(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    export_root = tmp_path / "export"
    datadir = export_root / "demo_map_3d"
    datadir.mkdir(parents=True)
    visible_file = datadir / "flight.csv"
    visible_file.write_text("metric,lat,long,alt\n1,43.0,1.0,1000\n", encoding="utf-8")
    hidden_file = datadir / ".hidden" / "hidden.csv"
    hidden_file.parent.mkdir(parents=True)
    hidden_file.write_text("metric,lat,long,alt\n2,44.0,2.0,1100\n", encoding="utf-8")

    share_root = tmp_path / "share"
    beamdir = share_root / "demo_map_3d"
    beamdir.mkdir(parents=True)
    beam_file = beamdir / "beam.csv"
    beam_file.write_text("beam,lat,long\n1,43.0,1.0\n", encoding="utf-8")
    hidden_beam = beamdir / ".hidden" / "beam.csv"
    hidden_beam.parent.mkdir(parents=True)
    hidden_beam.write_text("beam,lat,long\n1,43.0,1.0\n", encoding="utf-8")

    settings_path = tmp_path / "broken_settings.toml"
    settings_path.write_text("{ not = toml", encoding="utf-8")
    env = SimpleNamespace(
        app_settings_file=settings_path,
        target="demo_map_3d",
        projects=["demo_map_3d"],
        AGILAB_EXPORT_ABS=export_root,
        share_root_path=lambda: share_root,
    )
    fake_st = _FakeStreamlit(
        widget_values={
            ("sidebar.radio", "Dataset selection"): "Regex (multi)",
            ("sidebar.text_input", "DataFrame filename regex"): "flight",
            ("sidebar.button", module._vm3d_key("df_regex_select_all")): True,
            ("sidebar.multiselect", module._vm3d_key("beam_files")): "beam.csv",
        }
    )
    fake_st.session_state["env"] = env
    fake_st.session_state["df_files_selected"] = ["flight.csv"]
    fake_st.session_state["beam_files"] = "beam.csv"

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_list_dataset_files", lambda *_args, **_kwargs: [visible_file, hidden_file])
    monkeypatch.setattr(
        module,
        "find_files",
        lambda base, *args, **kwargs: [beam_file, hidden_beam] if Path(base) == beamdir else [],
    )
    monkeypatch.setattr(module, "load_df", lambda *_args, **_kwargs: pd.DataFrame())

    module.page()

    assert any("Some selected files failed to load" in message for message in fake_st.calls["sidebar.warning"])
    assert any("No selected dataframes could be loaded." in message for message in fake_st.calls["error"])
    assert fake_st.session_state[module._vm3d_key("df_files_selected")] == ["flight.csv"]
    assert fake_st.session_state["beam_files"] == []


def test_view_maps_3d_page_handles_persist_and_default_color_fallbacks(monkeypatch, tmp_path) -> None:
    module = _load_view_maps_3d_module()
    export_root = tmp_path / "export"
    datadir = export_root / "demo_map_3d"
    datadir.mkdir(parents=True)
    dataset_path = datadir / "flight.csv"
    dataset_path.write_text("cluster_id,metric,lat,long,alt\n0,0,43.0,1.0,1000\n", encoding="utf-8")
    dataset_df = pd.DataFrame(
        {
            "cluster_id": [idx % 2 for idx in range(25)],
            "metric": list(range(25)),
            "lat": [43.0 + idx * 0.01 for idx in range(25)],
            "long": [1.0 + idx * 0.01 for idx in range(25)],
            "alt": [1000 + idx * 10 for idx in range(25)],
        }
    )

    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text('view_maps_3d = "bad"\n', encoding="utf-8")
    env = SimpleNamespace(
        app_settings_file=settings_path,
        target="demo_map_3d",
        projects=["demo_map_3d"],
        AGILAB_EXPORT_ABS=export_root,
        share_root_path=lambda: tmp_path / "missing_share",
    )
    fake_st = _FakeStreamlit(
        widget_values={
            ("multiselect", "Select Layers"): ["Terrain"],
            ("selectbox", "discrete"): "missing_column",
        }
    )
    fake_st.session_state["env"] = env
    fake_st.session_state["coltype"] = "discrete"

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "_list_dataset_files", lambda *_args, **_kwargs: [dataset_path])
    monkeypatch.setattr(module, "load_df", lambda *_args, **_kwargs: dataset_df.copy())
    monkeypatch.setattr(
        module,
        "_dump_toml_payload",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("cannot write")),
    )

    module.page()

    assert settings_path.exists()
    assert settings_path.read_text(encoding="utf-8") == ""
    assert fake_st.session_state[module._vm3d_key("table_max_rows")] >= 10
    assert any(fake_st.calls["pydeck_chart"])
