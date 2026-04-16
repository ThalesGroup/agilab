from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path("src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py")

BARVIZ_STUB = """
from types import SimpleNamespace


class Attributes:
    def __init__(self, attrs=None, defaults=None):
        attrs = attrs or {}
        self.renderer = attrs.get("renderer", "streamlit")
        self.width = attrs.get("width", 640)
        self.height = attrs.get("height", 480)
        self.save_scale = attrs.get("save_scale", 1)
        self.markers_colormap = attrs.get("markers_colormap", {"cmax": None})
        self.lines_colormap = attrs.get("lines_colormap", {"cmax": None})
        self.lines_visible = attrs.get("lines_visible", True)
        self.markers_size = attrs.get("markers_size", None)
        self.markers_opacity = attrs.get("markers_opacity", None)
        self.markers_border_width = attrs.get("markers_border_width", None)
        self.text_size = attrs.get("text_size", None)


class _SimplexBase:
    def __init__(self, points=None, name="unknown", colors=None, labels=None, attrs=None):
        self.points = points
        self.name = name
        self.colors = colors or []
        self.labels = labels or []
        self.nbp = len(points) if points is not None else 0
        self.attrs = Attributes(attrs or {}, {})

    def get_skeleton(self):
        return "skeleton"


class Simplex(_SimplexBase):
    version = "1.0"
    _attributes_default = {}


class Collection:
    def __init__(self, points, labels, colors=None):
        self.points = points
        self.labels = labels
        self.colors = colors
        self.attrs = SimpleNamespace(
            markers_colormap={},
            markers_opacity=None,
            markers_size=None,
            markers_border_width=None,
        )


class Scrawler:
    def __init__(self, simplex):
        self.simplex = simplex

    def _trace_collection(self, item):
        return [item]

    def _get_layout(self):
        return {"title": "layout"}

    def update_center(self, observed_point):
        self.observed_point = observed_point

    def plot_save(self, save_as):
        self.saved_path = save_as
"""


class _State(dict):
    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:
            raise AttributeError(item) from exc

    def __setattr__(self, item, value):
        self[item] = value


def _load_module():
    fake_barviz = ModuleType("barviz")
    exec(BARVIZ_STUB, fake_barviz.__dict__)

    fake_sklearn = ModuleType("sklearn")
    fake_preprocessing = ModuleType("sklearn.preprocessing")
    fake_scipy = ModuleType("scipy")
    fake_signal = ModuleType("scipy.signal")

    class _StandardScaler:
        def fit_transform(self, data):
            return data

    fake_preprocessing.StandardScaler = _StandardScaler
    fake_sklearn.preprocessing = fake_preprocessing
    fake_signal.savgol_filter = lambda values, window_length, polyorder: values
    fake_scipy.signal = fake_signal

    spec = importlib.util.spec_from_file_location("view_barycentric_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(
        sys.modules,
        {
            "barviz": fake_barviz,
            "sklearn": fake_sklearn,
            "sklearn.preprocessing": fake_preprocessing,
            "scipy": fake_scipy,
            "scipy.signal": fake_signal,
        },
    ):
        spec.loader.exec_module(module)
    return module


def _seed_fake_page_deps(monkeypatch, tmp_path: Path) -> None:
    fake_root = tmp_path / "fake_page_deps"
    sklearn_pkg = fake_root / "sklearn"
    scipy_pkg = fake_root / "scipy"
    sklearn_pkg.mkdir(parents=True, exist_ok=True)
    scipy_pkg.mkdir(parents=True, exist_ok=True)
    (fake_root / "barviz.py").write_text(BARVIZ_STUB, encoding="utf-8")
    (sklearn_pkg / "__init__.py").write_text("", encoding="utf-8")
    (sklearn_pkg / "preprocessing.py").write_text(
        "class StandardScaler:\n"
        "    def fit_transform(self, data):\n"
        "        return data\n",
        encoding="utf-8",
    )
    (scipy_pkg / "__init__.py").write_text("", encoding="utf-8")
    (scipy_pkg / "signal.py").write_text(
        "def savgol_filter(values, window_length, polyorder):\n"
        "    return values\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(fake_root))


def test_maybe_smooth_long_column_skips_small_series() -> None:
    module = _load_module()
    df = pd.DataFrame({"long": [1.0, 2.0, 3.0, 4.0]})

    module._maybe_smooth_long_column(df)

    assert df["long"].tolist() == [1.0, 2.0, 3.0, 4.0]


def test_maybe_smooth_long_column_updates_valid_values(monkeypatch) -> None:
    module = _load_module()
    df = pd.DataFrame({"long": [1.0, 2.0, 3.0, 4.0, 5.0, None]})

    def fake_filter(values, window_length, polyorder):
        assert window_length == 5
        assert polyorder == 2
        return [42.0] * len(values)

    monkeypatch.setattr(module, "savgol_filter", fake_filter)

    module._maybe_smooth_long_column(df)

    assert df["long"].tolist()[:5] == [42.0, 42.0, 42.0, 42.0, 42.0]
    assert pd.isna(df["long"].iloc[5])


def test_maybe_smooth_long_column_handles_missing_column_and_filter_errors(monkeypatch) -> None:
    module = _load_module()
    no_long = pd.DataFrame({"lat": [1.0, 2.0, 3.0]})
    module._maybe_smooth_long_column(no_long)
    assert list(no_long.columns) == ["lat"]

    df = pd.DataFrame({"long": [1.0, 2.0, 3.0, 4.0, 5.0]})
    monkeypatch.setattr(
        module,
        "savgol_filter",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad window")),
    )
    module._maybe_smooth_long_column(df)
    assert df["long"].tolist() == [1.0, 2.0, 3.0, 4.0, 5.0]


def test_normalize_data_fills_missing_values() -> None:
    module = _load_module()
    df = pd.DataFrame({"x": [1.0, None], "y": [2.0, 4.0]})

    normalized = module.__normalize_data(df)

    assert normalized.equals(pd.DataFrame({"x": [1.0, 0.0], "y": [2.0, 4.0]}))


def test_modified_simplex_creates_expected_points() -> None:
    module = _load_module()
    simplex = module.ModifiedSimplex.__new__(module.ModifiedSimplex)

    points = simplex._ModifiedSimplex__create_simplex_points(4)

    assert points.shape == (4, 3)
    assert np.isclose(points[0][1], 1.0)
    assert np.isclose(points[-1][1], -1.0)


def test_modified_simplex_initializes_defaults_with_stubbed_barviz() -> None:
    module = _load_module()

    simplex = module.ModifiedSimplex(n_points=4, name="demo")

    assert simplex.points.shape == (4, 3)
    assert simplex.labels == ["P0", "P1", "P2", "P3"]
    assert simplex.colors == [0, 1, 2, 3]
    assert simplex.attrs.markers_colormap["cmax"] == 3
    assert simplex.attrs.lines_colormap["cmax"] == 3


def test_modified_scrawler_plot_updates_center_and_saves(monkeypatch) -> None:
    module = _load_module()
    charts: list[tuple[object, dict, str]] = []
    saved: list[str] = []
    centers: list[tuple[int, int, int]] = []

    scrawler = module.ModifiedScrawler.__new__(module.ModifiedScrawler)
    simplex = module.Simplex(
        points=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
        name="demo",
        attrs={"renderer": "plotly"},
    )
    scrawler.simplex = simplex

    monkeypatch.setattr(
        scrawler,
        "_trace_collection",
        lambda item: [module.go.Scatter(x=[0], y=[0], name=str(item))],
    )
    monkeypatch.setattr(scrawler, "_get_layout", lambda: {"title": "demo"})
    monkeypatch.setattr(scrawler, "plot_save", lambda save_as: saved.append(save_as))
    monkeypatch.setattr(scrawler, "update_center", lambda observed_point: centers.append(observed_point))
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(plotly_chart=lambda fig, config=None, renderer=None: charts.append((fig, config, renderer))),
    )

    scrawler.plot("payload", save_as="figure.svg", observed_point=(1, 2, 3), format="svg")

    assert centers == [(1, 2, 3)]
    assert saved == ["figure.svg"]
    assert charts[0][1]["toImageButtonOptions"]["format"] == "svg"
    assert charts[0][2] == "plotly"
    assert scrawler.fig.data


def test_bary_visualisation_supports_colored_and_plain_modes(monkeypatch) -> None:
    module = _load_module()

    class FakeCollection:
        def __init__(self, points, labels, colors=None):
            self.points = points
            self.labels = labels
            self.colors = colors
            self.attrs = SimpleNamespace(
                markers_colormap={},
                markers_opacity=None,
                markers_size=None,
                markers_border_width=None,
            )

    plotted: dict[str, object] = {}

    class FakeSimplex:
        def __init__(self, n_points, name, labels):
            self.attrs = SimpleNamespace(
                lines_visible=True,
                markers_size=None,
                markers_colormap={},
                width=None,
                height=None,
                text_size=None,
            )
            self.labels = labels

        def plot(self, collection, format="png"):
            plotted["collection"] = collection
            plotted["format"] = format

    writes: list[object] = []
    headers: list[str] = []
    state = _State(
        loaded_df=pd.DataFrame(
            {
                "slot": [1, 2],
                "value": [3.0, 4.0],
                "numeric_color": [10.0, 20.0],
            }
        )
    )
    monkeypatch.setattr(module, "Collection", FakeCollection)
    monkeypatch.setattr(module, "ModifiedSimplex", FakeSimplex)
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=state,
            header=headers.append,
            write=lambda value: writes.append(value),
            selectbox=lambda label, label_visibility=None, options=None: options[0],
        ),
    )

    bary_df = pd.DataFrame({"alpha": [1.0, 2.0], "beta": [3.0, 4.0]})
    module.__bary_visualisation(
        bary_df,
        selected_format="png",
        selected_name="demo",
        selected_x1="slot",
        selected_x2="value",
        color="numeric_color",
    )

    assert headers == ["slot per value"]
    assert plotted["format"] == "png"
    assert plotted["collection"].attrs.markers_colormap["colorscale"] == "Blues"
    assert isinstance(writes[0], pd.DataFrame)
    assert isinstance(writes[-1], pd.DataFrame)

    writes.clear()
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=state,
            header=headers.append,
            write=lambda value: writes.append(value),
            selectbox=lambda label, label_visibility=None, options=None: options[1],
        ),
    )

    module.__bary_visualisation(
        bary_df,
        selected_format="svg",
        selected_name="demo",
        selected_x1="slot",
        selected_x2="value",
        color=None,
    )

    assert plotted["format"] == "svg"
    assert plotted["collection"].attrs.markers_colormap["colorscale"] == ["blue", "blue"]
    barycentric_table = writes[-1]
    assert np.allclose(barycentric_table.sum(axis=1).to_numpy(), np.ones(len(barycentric_table)))


def test_bary_visualisation_handles_categorical_colors_and_jump(monkeypatch) -> None:
    module = _load_module()

    class FakeCollection:
        def __init__(self, points, labels, colors=None):
            self.points = points
            self.labels = labels
            self.colors = colors
            self.attrs = SimpleNamespace(
                markers_colormap={},
                markers_opacity=None,
                markers_size=None,
                markers_border_width=None,
            )

    class FakeSimplex:
        def __init__(self, n_points, name, labels):
            self.attrs = SimpleNamespace(
                lines_visible=True,
                markers_size=None,
                markers_colormap={},
                width=None,
                height=None,
                text_size=None,
            )

        def plot(self, *args, **kwargs):
            return None

    class _Jump(RuntimeError):
        pass

    session_state = _State(
        loaded_df=pd.DataFrame(
            {
                "slot": [1, 2],
                "value": [3.0, 4.0],
                "color_name": ["blue", "red"],
            }
        )
    )

    monkeypatch.setattr(module, "Collection", FakeCollection)
    monkeypatch.setattr(module, "ModifiedSimplex", FakeSimplex)
    monkeypatch.setattr(module, "JumpToMain", lambda exc: (_ for _ in ()).throw(_Jump(str(exc))))

    def fail_write(_value):
        raise ValueError("write failed")

    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=session_state,
            header=lambda *_args, **_kwargs: None,
            write=fail_write,
            selectbox=lambda label, label_visibility=None, options=None: options[0],
        ),
    )

    with pytest.raises(_Jump):
        module.__bary_visualisation(
            pd.DataFrame({"alpha": [1.0, 2.0], "beta": [3.0, 4.0]}),
            selected_format="png",
            selected_name="demo",
            selected_x1="slot",
            selected_x2="value",
            color="color_name",
        )


def test_page_handles_load_failure(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    datadir = tmp_path / "data"
    datadir.mkdir()
    data_file = datadir / "dataset.csv"
    data_file.write_text("a,b\n1,2\n", encoding="utf-8")
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("", encoding="utf-8")

    errors: list[str] = []
    warnings: list[str] = []
    session_state = _State(datadir=str(datadir), df_file="dataset.csv")
    sidebar = SimpleNamespace(
        text_input=lambda *args, **kwargs: None,
        selectbox=lambda *args, **kwargs: None,
        error=errors.append,
    )
    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [data_file])
    monkeypatch.setattr(module, "load_df", lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("boom")))
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=session_state,
            sidebar=sidebar,
            warning=warnings.append,
            error=errors.append,
        ),
    )

    env = SimpleNamespace(target="demo_bary", projects=["demo_bary"], app_settings_file=settings_path)
    module.page(env)

    assert any("Error loading data: boom" in message for message in errors)
    assert any("could not be loaded" in message for message in warnings)


def test_view_barycentric_warns_when_data_dir_missing(
    tmp_path: Path, monkeypatch, create_temp_app_project, run_page_app_test
) -> None:
    _seed_fake_page_deps(monkeypatch, tmp_path)
    missing_data_dir = tmp_path / "missing-data"
    project_dir = create_temp_app_project(
        "demo_bary_project",
        "demo_bary",
        f"[view_barycentric]\n" f'datadir = "{missing_data_dir.as_posix()}"\n',
        pyproject_name="demo-bary-project",
    )

    at = run_page_app_test(str(MODULE_PATH), project_dir)

    assert not at.exception
    assert any("Barycentric Graph" in title.value for title in at.title)
    assert any("A valid data directory is required to proceed." in warning.value for warning in at.warning)


def test_page_with_single_distinct_axis_shows_info(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    datadir = tmp_path / "bary-data"
    datadir.mkdir()
    data_file = datadir / "dataset.csv"
    data_file.write_text("constant_axis,value_axis,color_axis\n", encoding="utf-8")
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        "[view_barycentric]\n"
        "variables = ['constant_axis', 'value_axis', 'color_axis']\n",
        encoding="utf-8",
    )

    dataset = pd.DataFrame(
        {
            "constant_axis": [1] * 100,
            "value_axis": np.arange(100),
            "color_axis": np.arange(100),
        }
    )
    infos: list[str] = []

    class _ColumnContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    session_state = _State(datadir=str(datadir), df_file="dataset.csv")
    sidebar = SimpleNamespace(
        text_input=lambda *args, **kwargs: None,
        selectbox=lambda *args, **kwargs: session_state["df_file"],
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [data_file])
    monkeypatch.setattr(module, "load_df", lambda *_args, **_kwargs: dataset.copy())
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=session_state,
            sidebar=sidebar,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            slider=lambda *args, **kwargs: 10,
            markdown=lambda *args, **kwargs: None,
            columns=lambda n: [_ColumnContext() for _ in range(n)],
            selectbox=lambda label, options, **kwargs: {
                "Correlated variables pair": "constant_axis",
                "Correlated variables": "value_axis",
                "Color": "color_axis",
                "Format": "png",
            }.get(label, options[0] if options else None),
            text_input=lambda *args, **kwargs: "figure",
            info=infos.append,
        ),
    )

    env = SimpleNamespace(target="demo_bary", projects=["demo_bary"], app_settings_file=settings_path)
    module.page(env)

    assert any("only 1 distinct value" in message for message in infos)


def test_page_warns_when_no_files_or_no_selection(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    datadir = tmp_path / "data"
    datadir.mkdir()
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("", encoding="utf-8")
    warnings: list[str] = []

    class _StopCalled(RuntimeError):
        pass

    sidebar = SimpleNamespace(
        text_input=lambda *args, **kwargs: None,
        selectbox=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=_State(datadir=str(datadir)),
            sidebar=sidebar,
            warning=warnings.append,
            error=lambda *args, **kwargs: None,
            stop=lambda: (_ for _ in ()).throw(_StopCalled()),
        ),
    )
    env = SimpleNamespace(target="demo_bary", projects=["demo_bary"], app_settings_file=settings_path)
    with pytest.raises(_StopCalled):
        module.page(env)
    assert any("dataset is required" in message.lower() for message in warnings)

    warnings.clear()
    data_file = datadir / "dataset.csv"
    data_file.write_text("a,b\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [data_file])
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=_State(datadir=str(datadir)),
            sidebar=sidebar,
            warning=warnings.append,
            error=lambda *args, **kwargs: None,
        ),
    )
    module.page(env)
    assert any("Please select a dataset" in message for message in warnings)


def test_page_warns_when_loaded_df_invalid(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    datadir = tmp_path / "data"
    datadir.mkdir()
    data_file = datadir / "dataset.csv"
    data_file.write_text("a,b\n1,2\n", encoding="utf-8")
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("", encoding="utf-8")
    warnings: list[str] = []

    sidebar = SimpleNamespace(
        text_input=lambda *args, **kwargs: None,
        selectbox=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [data_file])
    monkeypatch.setattr(module, "load_df", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=_State(datadir=str(datadir), df_file="dataset.csv"),
            sidebar=sidebar,
            warning=warnings.append,
            error=lambda *args, **kwargs: None,
        ),
    )
    env = SimpleNamespace(target="demo_bary", projects=["demo_bary"], app_settings_file=settings_path)
    module.page(env)
    assert any("dataset is empty" in message.lower() for message in warnings)


def test_view_barycentric_page_seeds_df_file_from_persisted_settings(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    datadir = tmp_path / "data"
    datadir.mkdir()
    data_file = datadir / "dataset.csv"
    data_file.write_text("axis_a,axis_b,color_axis\n0,1,blue\n1,2,blue\n", encoding="utf-8")
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        "[view_barycentric]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'df_file = "dataset.csv"\n',
        encoding="utf-8",
    )

    dataset = pd.DataFrame(
        {
            "axis_a": list(range(10)),
            "axis_b": list(range(10, 20)),
            "color_axis": ["blue"] * 10,
        }
    )

    class _ColumnContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    session_state = _State()
    sidebar = SimpleNamespace(
        text_input=lambda *args, **kwargs: None,
        selectbox=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [data_file])
    monkeypatch.setattr(module, "load_df", lambda *_args, **_kwargs: dataset.copy())
    monkeypatch.setattr(module, "__bary_visualisation", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=session_state,
            sidebar=sidebar,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            slider=lambda *args, **kwargs: 10,
            markdown=lambda *args, **kwargs: None,
            columns=lambda n: [_ColumnContext() for _ in range(n)],
            selectbox=lambda label, options, **kwargs: {
                "Correlated variables pair": "axis_a",
                "Correlated variables": "axis_b",
                "Color": "color_axis",
                "Format": "png",
            }.get(label, options[0] if options else None),
            text_input=lambda *args, **kwargs: "figure",
            info=lambda *args, **kwargs: None,
        ),
    )

    env = SimpleNamespace(target="demo_bary", projects=["demo_bary"], app_settings_file=settings_path)
    module.page(env)

    assert session_state["datadir"] == str(datadir)
    assert session_state["df_file"] == "dataset.csv"


def test_view_barycentric_main_reports_missing_app_and_page_errors(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    errors: list[str] = []

    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(session_state=_State(), error=errors.append),
    )
    monkeypatch.setattr(module.sys, "argv", ["view_barycentric.py", "--active-app", str(tmp_path / "missing_app")])
    with pytest.raises(SystemExit):
        module.main()
    assert any("provided --active-app path not found" in message.lower() for message in errors)

    errors.clear()
    active_app = tmp_path / "apps" / "demo_project"
    active_app.mkdir(parents=True)

    class FakeEnv:
        def __init__(self, apps_path, app, verbose):
            self.apps_path = apps_path
            self.app = app
            self.verbose = verbose
            self.TABLE_MAX_ROWS = 10
            self.GUI_SAMPLING = 1
            self.is_source_env = True
            self.is_worker_env = False

    monkeypatch.setattr(module, "AgiEnv", FakeEnv)
    monkeypatch.setattr(module, "page", lambda env: (_ for _ in ()).throw(RuntimeError("page boom")))
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(session_state=_State(), error=errors.append),
    )
    monkeypatch.setattr(module.sys, "argv", ["view_barycentric.py", "--active-app", str(active_app)])
    module.main()
    assert any("page boom" in message for message in errors)


def test_view_barycentric_repo_path_and_visible_file_helpers(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    src_root = repo_root / "src"
    app_root = src_root / "agilab" / "apps-pages" / "view_barycentric" / "src" / "view_barycentric"
    app_root.mkdir(parents=True)
    module_path = app_root / "view_barycentric.py"
    module_path.write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(module, "__file__", str(module_path))
    monkeypatch.setattr(module.sys, "path", [])
    module._ensure_repo_on_path()

    assert str(src_root) in module.sys.path
    assert str(repo_root) in module.sys.path

    datadir = tmp_path / "data"
    datadir.mkdir()
    visible = datadir / "visible.csv"
    hidden = datadir / ".shadow" / "hidden.csv"
    outside = tmp_path / "outside.csv"
    visible.write_text("a,b\n1,2\n", encoding="utf-8")

    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("[broken", encoding="utf-8")
    warnings: list[str] = []
    session_state = _State(datadir=str(datadir), df_file="outside.csv")
    sidebar = SimpleNamespace(
        text_input=lambda *args, **kwargs: None,
        selectbox=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [visible, hidden, outside])
    monkeypatch.setattr(module, "load_df", lambda *_args, **_kwargs: pd.DataFrame())
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=session_state,
            sidebar=sidebar,
            warning=warnings.append,
            error=lambda *args, **kwargs: None,
        ),
    )
    env = SimpleNamespace(target="demo_bary", projects=["demo_bary"], app_settings_file=settings_path)
    module.page(env)

    assert session_state["csv_files"] == [visible, outside]
    assert any("dataset is empty" in message.lower() for message in warnings)


def test_view_barycentric_page_persists_and_calls_visualisation(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    datadir = tmp_path / "data"
    datadir.mkdir()
    data_file = datadir / "dataset.csv"
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("", encoding="utf-8")
    saved_payloads: list[dict] = []
    visualisation_calls: list[tuple[pd.DataFrame, str, str, str, str, str]] = []

    dataset = pd.DataFrame(
        {
            "axis_a": [0, 0, 1, 1, 2, 2, 3, 3, 4, 4],
            "axis_b": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
            "color_axis": ["blue"] * 10,
            "textual": ["x"] * 10,
        }
    )

    class _ColumnContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    session_state = _State(datadir=str(datadir), df_file="dataset.csv")
    sidebar = SimpleNamespace(
        text_input=lambda *args, **kwargs: None,
        selectbox=lambda *args, **kwargs: session_state["df_file"],
        error=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [data_file])
    monkeypatch.setattr(module, "load_df", lambda *_args, **_kwargs: dataset.copy())
    monkeypatch.setattr(module, "_maybe_smooth_long_column", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        module,
        "__bary_visualisation",
        lambda df, selected_format, selected_name, selected_x1, selected_x2, color=None: visualisation_calls.append(
            (df.copy(), selected_format, selected_name, selected_x1, selected_x2, color)
        ),
    )
    monkeypatch.setattr(
        module,
        "_dump_toml_payload",
        lambda payload, fh: (saved_payloads.append(payload), fh.write(b"[view_barycentric]\n")),
    )
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=session_state,
            sidebar=sidebar,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            slider=lambda *args, **kwargs: 10,
            markdown=lambda *args, **kwargs: None,
            columns=lambda n: [_ColumnContext() for _ in range(n)],
            selectbox=lambda label, options, **kwargs: {
                "Correlated variables pair": "axis_a",
                "Correlated variables": "axis_b",
                "Color": "color_axis",
                "Format": "png",
            }.get(label, options[0] if options else None),
            text_input=lambda *args, **kwargs: "figure",
            info=lambda *args, **kwargs: None,
        ),
    )

    env = SimpleNamespace(target="demo_bary", projects=["demo_bary"], app_settings_file=settings_path)
    module.page(env)

    assert visualisation_calls
    pivot_df, selected_format, selected_name, selected_x1, selected_x2, color = visualisation_calls[0]
    assert selected_format == "png"
    assert selected_name == "figure"
    assert (selected_x1, selected_x2, color) == ("axis_a", "axis_b", "color_axis")
    assert pivot_df.shape[1] > 1
    assert saved_payloads and saved_payloads[0]["view_barycentric"]["df_file"] == "dataset.csv"


def test_view_barycentric_page_seeds_persisted_df_file_and_tolerates_write_failures(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    datadir = tmp_path / "data"
    datadir.mkdir()
    data_file = datadir / "dataset.csv"
    data_file.write_text("axis_a,axis_b,color_axis\n1,2,blue\n2,3,blue\n3,4,blue\n4,5,blue\n5,6,blue\n", encoding="utf-8")
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text(
        "[view_barycentric]\n"
        f'datadir = "{datadir.as_posix()}"\n'
        'df_file = "dataset.csv"\n',
        encoding="utf-8",
    )

    class _ColumnContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    session_state = _State(datadir=str(datadir), df_file="dataset.csv")
    sidebar = SimpleNamespace(
        text_input=lambda *args, **kwargs: None,
        selectbox=lambda *args, **kwargs: session_state.get("df_file", "dataset.csv"),
        error=lambda *args, **kwargs: None,
    )

    monkeypatch.setattr(module, "find_files", lambda *_args, **_kwargs: [data_file])
    monkeypatch.setattr(
        module,
        "load_df",
        lambda *_args, **_kwargs: pd.DataFrame(
            {
                "axis_a": [0, 0, 1, 1, 2, 2],
                "axis_b": [10, 11, 12, 13, 14, 15],
                "color_axis": ["blue"] * 6,
            }
        ),
    )
    monkeypatch.setattr(module, "_maybe_smooth_long_column", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "__bary_visualisation", lambda *args, **kwargs: None)
    monkeypatch.setattr(module.Path, "mkdir", lambda *args, **kwargs: None, raising=False)
    monkeypatch.setattr(module, "open", lambda *args, **kwargs: (_ for _ in ()).throw(OSError("disk full")), raising=False)
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=session_state,
            sidebar=sidebar,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            slider=lambda *args, **kwargs: 10,
            markdown=lambda *args, **kwargs: None,
            columns=lambda n: [_ColumnContext() for _ in range(n)],
            selectbox=lambda label, options, **kwargs: {
                "Correlated variables pair": "axis_a",
                "Correlated variables": "axis_b",
                "Color": "color_axis",
                "Format": "png",
            }.get(label, options[0] if options else None),
            text_input=lambda *args, **kwargs: "figure",
            info=lambda *args, **kwargs: None,
        ),
    )

    env = SimpleNamespace(target="demo_bary", projects=["demo_bary"], app_settings_file=settings_path)
    module.page(env)

    assert session_state["df_file"] == "dataset.csv"


def test_view_barycentric_main_reports_outer_exception(monkeypatch) -> None:
    module = _load_module()
    errors: list[str] = []

    monkeypatch.setattr(module.argparse, "ArgumentParser", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("arg boom")))
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=_State(), error=errors.append))

    module.main()

    assert any("arg boom" in message for message in errors)
