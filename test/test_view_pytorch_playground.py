from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(
    "src/agilab/apps-pages/view_pytorch_playground/src/view_pytorch_playground/view_pytorch_playground.py"
)
INIT_PATH = Path("src/agilab/apps-pages/view_pytorch_playground/src/view_pytorch_playground/__init__.py")
README_PATH = Path("src/agilab/apps-pages/README.md")


def _load_module():
    spec = importlib.util.spec_from_file_location("view_pytorch_playground_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_pytorch_playground_dataset_generation_is_deterministic() -> None:
    module = _load_module()
    config = module.PlaygroundConfig(dataset="xor", sample_count=48, noise=0.04, seed=17)

    first = module._make_dataset(config)
    second = module._make_dataset(config)

    pd.testing.assert_frame_equal(first, second)
    assert list(first.columns) == ["x1", "x2", "target"]
    assert sorted(first["target"].unique().tolist()) == [0, 1]


def test_pytorch_playground_feature_matrix_uses_selected_features() -> None:
    module = _load_module()
    samples = pd.DataFrame({"x1": [1.0, -0.5], "x2": [2.0, 0.25]})

    matrix = module._feature_matrix(samples, ("x1", "x2_squared", "x1_x2", "sin_x2"))

    np.testing.assert_allclose(
        matrix,
        np.array(
            [
                [1.0, 4.0, 2.0, 0.0],
                [-0.5, 0.0625, -0.125, np.sin(np.pi * 0.25)],
            ],
            dtype=np.float32,
        ),
        atol=1e-7,
    )


def test_pytorch_playground_hidden_layer_parser_validates_bounds() -> None:
    module = _load_module()

    assert module._parse_hidden_layers("8, 16;32") == (8, 16, 32)
    assert module._parse_hidden_layers(" ") == ()

    with pytest.raises(ValueError, match="integer"):
        module._parse_hidden_layers("8,wide")
    with pytest.raises(ValueError, match="between 1 and 256"):
        module._parse_hidden_layers("0")
    with pytest.raises(ValueError, match="at most six"):
        module._parse_hidden_layers("1,2,3,4,5,6,7")


def test_pytorch_playground_reports_missing_torch(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "torch", None)
    monkeypatch.setattr(module, "nn", None)
    config = module.PlaygroundConfig(sample_count=32, epochs=1, grid_size=12)

    result = module._train_playground(config)

    assert result["status"] == "missing_torch"
    assert result["samples"].shape[0] == 32
    assert result["history"].empty
    assert result["grid"].empty
    assert result["summary"]["backend"] == "missing"


def test_pytorch_playground_training_smoke_when_torch_is_available() -> None:
    module = _load_module()
    if module.torch is None:
        pytest.skip("torch is not installed in this validation environment")

    config = module.PlaygroundConfig(
        dataset="gaussian",
        sample_count=40,
        hidden_layers=(4,),
        epochs=2,
        batch_size=16,
        feature_names=("x1", "x2"),
        grid_size=12,
        seed=3,
    )

    result = module._train_playground(config)

    assert result["status"] == "ok"
    assert not result["history"].empty
    assert result["grid"].shape[0] == 144
    assert 0.0 <= result["summary"]["validation_accuracy"] <= 1.0
    assert result["summary"]["backend"] == "torch"


def test_pytorch_playground_bundle_root_and_source_only_docs() -> None:
    spec = importlib.util.spec_from_file_location("view_pytorch_playground_init_test_module", INIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    assert module.bundle_root() == INIT_PATH.parent.resolve()
    readme = README_PATH.read_text(encoding="utf-8")
    assert "view_pytorch_playground" in readme
    assert "not part of the public `agi-pages` umbrella" in readme
