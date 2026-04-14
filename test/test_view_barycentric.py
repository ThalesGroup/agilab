from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd


MODULE_PATH = Path("src/agilab/apps-pages/view_barycentric/src/view_barycentric/view_barycentric.py")


def _load_module():
    fake_barviz = ModuleType("barviz")
    fake_barviz.Simplex = type("Simplex", (), {})
    fake_barviz.Collection = type("Collection", (), {})
    fake_barviz.Scrawler = type("Scrawler", (), {})
    fake_barviz.Attributes = type("Attributes", (), {})

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
    (fake_root / "barviz.py").write_text(
        "class Simplex: ...\n"
        "class Collection: ...\n"
        "class Scrawler: ...\n"
        "class Attributes: ...\n",
        encoding="utf-8",
    )
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
