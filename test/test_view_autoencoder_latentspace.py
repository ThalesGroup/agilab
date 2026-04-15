from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/autoencoder_latentspace.py"
)

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

    spec = importlib.util.spec_from_file_location("view_autoencoder_latentspace_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"barviz": fake_barviz}):
        spec.loader.exec_module(module)
    return module


def _seed_fake_page_deps(monkeypatch, tmp_path: Path) -> None:
    fake_root = tmp_path / "fake_page_deps"
    fake_root.mkdir(parents=True, exist_ok=True)
    (fake_root / "barviz.py").write_text(BARVIZ_STUB, encoding="utf-8")
    monkeypatch.syspath_prepend(str(fake_root))


def test_update_datadir_clears_selected_file_state(monkeypatch) -> None:
    module = _load_module()
    session_state = {
        "df_file": "obsolete.csv",
        "csv_files": ["obsolete.csv"],
        "input_datadir": "/tmp/new-data",
    }
    initialize_calls: list[str] = []

    monkeypatch.setattr(module, "st", SimpleNamespace(session_state=session_state))
    monkeypatch.setattr(module, "initialize_csv_files", lambda: initialize_calls.append("called"))

    module.update_datadir("datadir", "input_datadir")

    assert "df_file" not in session_state
    assert "csv_files" not in session_state
    assert session_state["datadir"] == "/tmp/new-data"
    assert initialize_calls == ["called"]


def test_lazy_import_helpers_and_normalize_data(monkeypatch) -> None:
    module = _load_module()

    fake_plotly = ModuleType("plotly")
    fake_plotly.__path__ = []  # type: ignore[attr-defined]
    fake_graph_objects = ModuleType("plotly.graph_objects")
    fake_graph_objects.Figure = type("Figure", (), {})
    fake_plotly.graph_objects = fake_graph_objects

    fake_barviz = ModuleType("barviz")
    fake_barviz.Simplex = type("Simplex", (), {})
    fake_barviz.Collection = type("Collection", (), {})
    fake_barviz.Scrawler = type("Scrawler", (), {})
    fake_barviz.Attributes = type("Attributes", (), {})

    fake_keras = ModuleType("keras")
    fake_keras.__path__ = []  # type: ignore[attr-defined]
    fake_keras.Sequential = type("Sequential", (), {})
    fake_keras_callbacks = ModuleType("keras.callbacks")
    fake_keras_callbacks.EarlyStopping = type("EarlyStopping", (), {})
    fake_keras_layers = ModuleType("keras.layers")
    fake_keras_layers.Dense = type("Dense", (), {})
    fake_keras.callbacks = fake_keras_callbacks
    fake_keras.layers = fake_keras_layers

    fake_sklearn = ModuleType("sklearn")
    fake_sklearn.__path__ = []  # type: ignore[attr-defined]
    fake_sklearn_model_selection = ModuleType("sklearn.model_selection")
    fake_sklearn_model_selection.train_test_split = object()

    class _StandardScaler:
        def fit_transform(self, data):
            return data.fillna(0)

    fake_sklearn_preprocessing = ModuleType("sklearn.preprocessing")
    fake_sklearn_preprocessing.StandardScaler = _StandardScaler
    fake_sklearn.model_selection = fake_sklearn_model_selection
    fake_sklearn.preprocessing = fake_sklearn_preprocessing

    with patch.dict(
        sys.modules,
        {
            "plotly": fake_plotly,
            "plotly.graph_objects": fake_graph_objects,
            "barviz": fake_barviz,
            "keras": fake_keras,
            "keras.callbacks": fake_keras_callbacks,
            "keras.layers": fake_keras_layers,
            "sklearn": fake_sklearn,
            "sklearn.model_selection": fake_sklearn_model_selection,
            "sklearn.preprocessing": fake_sklearn_preprocessing,
        },
    ):
        go = module.lazy_import_plotly()
        assert go is fake_graph_objects
        assert module.lazy_import_barviz() == (
            fake_barviz.Simplex,
            fake_barviz.Collection,
            fake_barviz.Scrawler,
            fake_barviz.Attributes,
        )
        assert module.lazy_import_keras() == (
            fake_keras.Sequential,
            fake_keras_callbacks.EarlyStopping,
            fake_keras_layers.Dense,
        )
        assert module.lazy_import_sklearn() == (
            fake_sklearn_model_selection.train_test_split,
            _StandardScaler,
        )

        df = pd.DataFrame({"x": [1.0, None], "y": [2.0, 4.0]})
        normalized = module.__normalize_data(df)

    assert normalized.equals(pd.DataFrame({"x": [1.0, 0.0], "y": [2.0, 4.0]}))


def test_modified_simplex_and_scrawler_helpers(monkeypatch) -> None:
    module = _load_module()
    simplex = module.ModifiedSimplex(n_points=4, name="demo")

    assert simplex.points.shape == (4, 3)
    assert simplex.labels == ["P0", "P1", "P2", "P3"]
    assert simplex.colors == [0, 1, 2, 3]
    assert simplex.attrs.markers_colormap["cmax"] == 3
    assert simplex.attrs.lines_colormap["cmax"] == 3

    charts: list[tuple[object, dict, str]] = []
    centers: list[tuple[int, int, int]] = []
    saved: list[str] = []
    scrawler = module.ModifiedScrawler.__new__(module.ModifiedScrawler)
    scrawler.simplex = module.Simplex(
        points=np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0]]),
        name="demo",
        attrs={"renderer": "plotly"},
    )

    monkeypatch.setattr(
        scrawler,
        "_trace_collection",
        lambda item: [module.lazy_import_plotly().Scatter(x=[0], y=[0], name=str(item))],
    )
    monkeypatch.setattr(scrawler, "_get_layout", lambda: {"title": "demo"})
    monkeypatch.setattr(scrawler, "update_center", lambda observed_point: centers.append(observed_point))
    monkeypatch.setattr(scrawler, "plot_save", lambda save_as: saved.append(save_as))
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


def test_build_ae_builds_expected_dense_stack(monkeypatch) -> None:
    module = _load_module()
    added_layers: list[dict[str, object]] = []
    fit_calls: list[dict[str, object]] = []

    class FakeSequential:
        def __init__(self, layers=None):
            self.layers = list(layers or [])

        def add(self, layer):
            added_layers.append(layer)
            self.layers.append(layer)

        def compile(self, optimizer=None, loss=None):
            self.optimizer = optimizer
            self.loss = loss

        def fit(self, data, targets, **kwargs):
            fit_calls.append({"shape": data.shape, "kwargs": kwargs})

    def fake_dense(units, input_dim=None, activation=None):
        return {"units": units, "input_dim": input_dim, "activation": activation}

    def fake_early_stopping(metric, **kwargs):
        return {"metric": metric, **kwargs}

    monkeypatch.setattr(module, "lazy_import_keras", lambda: (FakeSequential, fake_early_stopping, fake_dense))

    data = np.ones((8, 4))
    model = module.build_AE(data, ndim=4, ndim_inter=3, ndim_middle=3)

    assert isinstance(model, FakeSequential)
    assert len(added_layers) == 6
    assert added_layers[0] == {"units": 3, "input_dim": 4, "activation": "relu"}
    assert added_layers[-1] == {"units": 4, "input_dim": None, "activation": "sigmoid"}
    assert fit_calls[0]["shape"] == (8, 4)
    assert fit_calls[0]["kwargs"]["validation_split"] == 0.2


def test_bary_visualisation_supports_color_and_plain_modes(monkeypatch) -> None:
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

    plotted: list[tuple[object, str]] = []
    tables: list[object] = []
    writes: list[object] = []
    markdowns: list[str] = []

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
            plotted.append((collection, format))

    monkeypatch.setattr(module, "Collection", FakeCollection)
    monkeypatch.setattr(module, "ModifiedSimplex", FakeSimplex)
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            selectbox=lambda label, options: list(options)[0],
            markdown=markdowns.append,
            table=lambda data: tables.append(data),
            write=lambda value: writes.append(value),
        ),
    )

    df = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
    color_data = pd.Series(["alpha", "beta"])
    module.__bary_visualisation(df, df.copy(), "label", "demo", "png", color_data=color_data)

    assert plotted[-1][1] == "png"
    assert plotted[-1][0].attrs.markers_colormap["colorscale"] == "Jet"
    assert markdowns[-1] == "**label:** alpha"
    assert isinstance(writes[-1], pd.DataFrame)

    plotted.clear()
    module.__bary_visualisation(df, df.copy(), "label", "demo", "svg", color_data=None)
    assert plotted[-1][1] == "svg"
    assert plotted[-1][0].attrs.markers_colormap["colorscale"] == ["blue", "blue"]


def test_page_handles_missing_and_empty_data(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("[view_autoencoder_latentspace]\ndatadir = \"/tmp/data\"\ndf_file = \"missing.csv\"\n", encoding="utf-8")
    warnings_seen: list[str] = []

    monkeypatch.setattr(module, "sidebar_views", lambda: None)
    monkeypatch.setattr(module, "load_df", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(session_state=_State(), warning=warnings_seen.append),
    )
    env = SimpleNamespace(target="demo", projects=["demo_project"], app_settings_file=settings_path)
    module.page(env)
    assert any("not found" in message for message in warnings_seen)

    warnings_seen.clear()
    monkeypatch.setattr(module, "load_df", lambda *args, **kwargs: pd.DataFrame())
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(session_state=_State(datadir="/tmp/data", df_file="empty.csv"), warning=warnings_seen.append),
    )
    module.page(env)
    assert any("empty or could not be loaded" in message for message in warnings_seen)


def test_page_runs_autoencoder_flow_and_persists_settings(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    settings_path = tmp_path / "app_settings.toml"
    settings_path.write_text("", encoding="utf-8")
    data = pd.DataFrame(
        {
            "x": [1.0 + i for i in range(12)],
            "y": [2.0 + i for i in range(12)],
            "label": [i % 2 for i in range(12)],
        }
    )
    calls: dict[str, object] = {}

    class FakeSequential:
        def __init__(self, layers=None):
            self.layers = list(layers or [])

        def predict(self, values, verbose=0):
            return np.column_stack((values[:, 0], values[:, 1]))

    monkeypatch.setattr(module, "sidebar_views", lambda: None)
    monkeypatch.setattr(module, "load_df", lambda *args, **kwargs: data.copy())
    monkeypatch.setattr(module, "lazy_import_keras", lambda: (FakeSequential, object, object))
    monkeypatch.setattr(
        module,
        "lazy_import_sklearn",
        lambda: (
            lambda X, y, test_size=0.2, random_state=42: (X[:8], X[8:], y.iloc[:8], y.iloc[8:]),
            object,
        ),
    )
    monkeypatch.setattr(module, "__normalize_data", lambda df: df.fillna(0))
    monkeypatch.setattr(
        module,
        "build_AE",
        lambda X_train, ndim, ndim_inter, ndim_middle: SimpleNamespace(layers=["enc1", "enc2", "latent", "dec1", "dec2"]),
    )
    monkeypatch.setattr(
        module,
        "__bary_visualisation",
        lambda df, X, selected_color, selected_name, selected_format, color_data=None: calls.update(
            {
                "df_shape": df.shape,
                "selected_color": selected_color,
                "selected_name": selected_name,
                "selected_format": selected_format,
                "color_len": len(color_data) if color_data is not None else None,
            }
        ),
    )

    class _ColumnContext:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    session_state = _State(datadir=str(tmp_path), df_file="data.csv", coltype="discrete")
    monkeypatch.setattr(
        module,
        "st",
        SimpleNamespace(
            session_state=session_state,
            slider=lambda *args, **kwargs: 10,
            columns=lambda n: [_ColumnContext() for _ in range(n)],
            number_input=lambda *args, **kwargs: 2,
            selectbox=lambda label, options, **kwargs: "label" if label == "Color" else options[0],
            text_input=lambda *args, **kwargs: "latent-demo",
            warning=lambda *args, **kwargs: None,
        ),
    )
    env = SimpleNamespace(target="demo", projects=["demo_project"], app_settings_file=settings_path)

    module.page(env)

    assert calls == {
        "df_shape": (8, 2),
        "selected_color": "label",
        "selected_name": "latent-demo",
        "selected_format": "png",
        "color_len": 8,
    }
    written = settings_path.read_text(encoding="utf-8")
    assert "view_autoencoder_latentspace" in written
    assert "df_file = \"data.csv\"" in written


def test_main_missing_active_app_sets_error(monkeypatch, tmp_path: Path) -> None:
    module = _load_module()
    errors: list[str] = []
    monkeypatch.setattr(module, "st", SimpleNamespace(session_state={}, error=errors.append))

    with patch("sys.argv", [MODULE_PATH.name, "--active-app", str(tmp_path / "missing")]):
        with pytest.raises(SystemExit):
            module.main()

    assert any("provided --active-app path not found" in message for message in errors)


def test_view_autoencoder_latentspace_smoke_renders(
    tmp_path: Path, monkeypatch, create_temp_app_project, run_page_app_test
) -> None:
    _seed_fake_page_deps(monkeypatch, tmp_path)
    data_dir = tmp_path / "autoencoder-data"
    data_dir.mkdir()
    (data_dir / "empty.csv").write_text("x,y\n", encoding="utf-8")
    project_dir = create_temp_app_project(
        "demo_autoencoder_project",
        "demo_autoencoder",
        "[view_autoencoder_latentspace]\n"
        f'datadir = "{data_dir.as_posix()}"\n'
        'df_file = "empty.csv"\n',
        pyproject_name="demo-autoencoder-project",
    )

    at = run_page_app_test(str(MODULE_PATH), project_dir)

    assert not at.exception
    assert any("Dimension Reduction" in title.value for title in at.title)
