from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pandas as pd


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_autoencoder_latenspace/src/view_autoencoder_latentspace/autoencoder_latentspace.py"
)


def _load_module():
    fake_barviz = ModuleType("barviz")
    fake_barviz.Simplex = type("Simplex", (), {})
    fake_barviz.Collection = type("Collection", (), {})
    fake_barviz.Scrawler = type("Scrawler", (), {})
    fake_barviz.Attributes = type("Attributes", (), {})

    spec = importlib.util.spec_from_file_location("view_autoencoder_latentspace_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"barviz": fake_barviz}):
        spec.loader.exec_module(module)
    return module


def _seed_fake_page_deps(monkeypatch, tmp_path: Path) -> None:
    fake_root = tmp_path / "fake_page_deps"
    fake_root.mkdir(parents=True, exist_ok=True)
    (fake_root / "barviz.py").write_text(
        "class Simplex: ...\n"
        "class Collection: ...\n"
        "class Scrawler: ...\n"
        "class Attributes: ...\n",
        encoding="utf-8",
    )
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
