from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

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
