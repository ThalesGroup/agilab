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
        default = options[index] if options else None
        return self._streamlit._widget_value("sidebar.selectbox", label, key=key, default=default, options=options)

    def radio(self, label, options, *args, key=None, index=0, **kwargs):
        default = options[index] if options else None
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
        default = options[index] if options else None
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
