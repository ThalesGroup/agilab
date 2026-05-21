from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import zipfile

import numpy as np
import pandas as pd
import pytest


MODULE_PATH = Path(
    "src/agilab/apps/builtin/pytorch_playground_project/src/pytorch_playground/playground_ui.py"
)
INIT_PATH = Path("src/agilab/lib/agi-app-pytorch-playground/src/agi_app_pytorch_playground/__init__.py")
README_PATH = Path("src/agilab/lib/agi-app-pytorch-playground/README.md")
PROJECT_PATH = Path("src/agilab/apps/builtin/pytorch_playground_project")
PACKAGE_PROJECT_PATH = Path(
    "src/agilab/lib/agi-app-pytorch-playground/src/agi_app_pytorch_playground/project/pytorch_playground_project"
)
PROJECT_SRC = PROJECT_PATH / "src"
EXPECTED_SOURCE_PAYLOAD_DIFFS = {Path("pytorch_playground_worker/pyproject.toml")}


def _load_module():
    spec = importlib.util.spec_from_file_location("pytorch_playground_app_test_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_playground_ui_import_prefers_package_when_streamlit_puts_script_dir_first(monkeypatch):
    script_dir = MODULE_PATH.resolve().parent
    project_src = PROJECT_SRC.resolve()
    original_modules = {
        name: module
        for name, module in sys.modules.items()
        if name == "pytorch_playground" or name.startswith("pytorch_playground.")
    }
    for name in original_modules:
        sys.modules.pop(name, None)

    fake_path = [
        str(script_dir),
        str(project_src),
        *[
            entry
            for entry in sys.path
            if entry not in {str(script_dir), str(project_src)}
        ],
    ]
    monkeypatch.setattr(sys, "path", fake_path)

    spec = importlib.util.spec_from_file_location("pytorch_playground_streamlit_path_order_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert sys.path[0] == str(project_src)
        assert module._playground_core.__name__ == "pytorch_playground.core"
    finally:
        sys.modules.pop(spec.name, None)
        for name in list(sys.modules):
            if name == "pytorch_playground" or name.startswith("pytorch_playground."):
                sys.modules.pop(name, None)
        sys.modules.update(original_modules)


def test_cached_train_uses_isolated_subprocess_in_streamlit_context() -> None:
    module = _load_module()
    if module.torch is None:
        pytest.skip("torch is not installed in this validation environment")

    from streamlit.testing.v1 import AppTest

    module_path = str(MODULE_PATH.resolve())
    script = f"""
from dataclasses import asdict
import importlib.util
from pathlib import Path
import sys

import streamlit as st

path = Path({module_path!r})
spec = importlib.util.spec_from_file_location("pytorch_playground_streamlit_subprocess_regression", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
config = module.PlaygroundConfig(sample_count=64, epochs=1, grid_size=12, hidden_layers=(4,))
result = module._cached_train(asdict(config))
st.write(f"status={{result['status']}}")
st.write(f"backend={{result['summary'].get('backend')}}")
"""
    app = AppTest.from_string(script, default_timeout=60)
    app.run()

    assert list(app.exception) == []
    assert [item.value for item in app.markdown] == ["status=ok", "backend=torch"]


def test_isolated_runner_success_serializes_request_and_pythonpath(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    config = module.PlaygroundConfig(sample_count=24, epochs=1, grid_size=8, hidden_layers=(4,))
    captured: dict[str, object] = {}

    def fake_run(cmd, **kwargs):
        input_path = Path(cmd[-2])
        output_path = Path(cmd[-1])
        request = module.pickle.loads(input_path.read_bytes())
        captured["request"] = request
        captured["pythonpath"] = kwargs["env"]["PYTHONPATH"]
        output_path.write_bytes(
            module.pickle.dumps(
                {"ok": True, "result": {"status": "ok", "summary": {"backend": "torch"}}},
                protocol=module.pickle.HIGHEST_PROTOCOL,
            )
        )
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    result = module._run_core_in_subprocess("train", config)

    assert result["status"] == "ok"
    assert result["summary"]["backend"] == "torch"
    assert captured["request"]["action"] == "train"
    assert captured["request"]["config"]["hidden_layers"] == (4,)
    assert str(module._APP_SRC) in str(captured["pythonpath"]).split(module.os.pathsep)


def test_isolated_runner_failure_paths_return_displayable_error_results(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    config = module.PlaygroundConfig(sample_count=20, epochs=1, grid_size=8)

    def timeout_run(*_args, **_kwargs):
        raise module.subprocess.TimeoutExpired(cmd="python", timeout=180)

    monkeypatch.setattr(module.subprocess, "run", timeout_run)
    train_timeout = module._run_core_in_subprocess("train", config)
    landscape_timeout = module._run_core_in_subprocess("loss_landscape", config, resolution=5, span=0.2)

    assert train_timeout["status"] == "error"
    assert "timed out after 180" in train_timeout["detail"]
    assert train_timeout["samples"].shape[0] == 20
    assert landscape_timeout["status"] == "error"
    assert landscape_timeout["loss_landscape"].empty

    def nonzero_run(_cmd, **_kwargs):
        return SimpleNamespace(returncode=7, stderr="fatal line\n")

    monkeypatch.setattr(module.subprocess, "run", nonzero_run)
    train_nonzero = module._run_core_in_subprocess("train", config)
    nonzero_result = module._run_core_in_subprocess("loss_landscape", config, resolution=5, span=0.2)
    assert train_nonzero["status"] == "error"
    assert train_nonzero["history"].empty
    assert nonzero_result["status"] == "error"
    assert "exit code 7" in nonzero_result["detail"]
    assert "fatal line" in nonzero_result["detail"]

    def payload_run(payload):
        def fake_run(cmd, **_kwargs):
            Path(cmd[-1]).write_bytes(module.pickle.dumps(payload, protocol=module.pickle.HIGHEST_PROTOCOL))
            return SimpleNamespace(returncode=0, stderr="")

        return fake_run

    monkeypatch.setattr(module.subprocess, "run", payload_run({"ok": False, "error_type": "ValueError", "error": "bad payload"}))
    failed_payload = module._run_core_in_subprocess("train", config)
    assert failed_payload["status"] == "error"
    assert "ValueError: bad payload" in failed_payload["detail"]

    monkeypatch.setattr(module.subprocess, "run", payload_run(["not", "a", "mapping"]))
    malformed_payload = module._run_core_in_subprocess("loss_landscape", config, resolution=5, span=0.2)
    assert malformed_payload["status"] == "error"
    assert malformed_payload["landscape_summary"]["status"] == "error"

    monkeypatch.setattr(module.subprocess, "run", payload_run({"ok": True, "result": []}))
    invalid_result = module._run_core_in_subprocess("train", config)
    invalid_landscape = module._run_core_in_subprocess("loss_landscape", config, resolution=5, span=0.2)
    assert invalid_result["status"] == "error"
    assert "runner returned an invalid payload" in invalid_result["detail"]
    assert invalid_landscape["status"] == "error"
    assert invalid_landscape["loss_landscape"].empty


def test_cached_train_and_loss_landscape_route_to_isolated_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    config = module.PlaygroundConfig(sample_count=28, epochs=1, grid_size=8, seed=101)
    calls: list[tuple[str, int | None, float | None]] = []

    def fake_run_core(action, _config, *, resolution=None, span=None):
        calls.append((action, resolution, span))
        if action == "train":
            return {"status": "ok", "summary": {"backend": "isolated"}}
        return {"status": "ok", "loss_landscape": pd.DataFrame(), "landscape_summary": {"points": 0}}

    monkeypatch.setattr(module, "_use_isolated_torch_training", lambda: True)
    monkeypatch.setattr(module, "_run_core_in_subprocess", fake_run_core)

    train_result = module._cached_train(module.asdict(config))
    landscape_result = module._cached_loss_landscape(module.asdict(config), resolution=7, span=0.3)

    assert train_result["summary"]["backend"] == "isolated"
    assert landscape_result["landscape_summary"]["points"] == 0
    assert calls == [("train", None, None), ("loss_landscape", 7, 0.3)]


def test_playground_ui_helper_error_and_display_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    fake_st = SimpleNamespace(session_state={module.TRAINED_CONFIG_STATE_KEY: "bad payload"})
    monkeypatch.setattr(module, "st", fake_st)

    config = module.PlaygroundConfig(sample_count=64, epochs=10, grid_size=12)
    trained, preset, pending = module._resolve_trained_config(
        config,
        module.DEFAULT_PRESET,
        train_requested=False,
    )

    assert trained == config
    assert preset == module.DEFAULT_PRESET
    assert pending is False
    assert module._streamlit_script_context_active() is False
    assert module._session_state_get("missing", "fallback") == "fallback"
    monkeypatch.setattr(module, "st", SimpleNamespace())
    assert module._session_state_get("missing", "fallback") == "fallback"
    assert module._format_percent("bad") == "0%"
    assert module._format_percent(float("nan")) == "0%"
    assert module._confidence_score(pd.DataFrame({"probability": []})) == 0.0
    assert module._class_balance(pd.DataFrame({"target": []})) == "no samples"
    assert module._performance_band({"validation_accuracy": 0.95})[0] == "Strong fit"
    assert module._performance_band({"validation_accuracy": 0.80})[0] == "Learning visible"
    assert module._gap_band({"train_accuracy": 0.90, "validation_accuracy": 0.80})[0] == "Watch the gap"
    assert module._gap_band({"train_accuracy": 0.95, "validation_accuracy": 0.70})[0] == "Likely overfit"
    assert module._confidence_band(pd.DataFrame({"probability": [0.1, 0.9]}))[0] == "Decisive boundary"
    assert module._confidence_band(pd.DataFrame({"probability": [0.30, 0.70]}))[0] == "Boundary forming"


def _runtime_payload_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
        and path.suffix not in {".c", ".pyx", ".so"}
        and "__pycache__" not in path.parts
        and ".venv" not in path.parts
        and path.suffix != ".pyc"
        and not any(part.endswith(".egg-info") for part in path.parts)
    }


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
    assert result["network_layers"].empty
    assert result["activation_maps"].empty
    assert result["summary"]["backend"] == "missing"
    landscape = module._loss_landscape(config, resolution=5, span=0.2)
    assert landscape["status"] == "missing_torch"
    assert landscape["loss_landscape"].empty


def test_pytorch_playground_share_config_round_trips_and_sanitizes() -> None:
    module = _load_module()
    config = module.PlaygroundConfig(
        dataset="spiral",
        sample_count=320,
        noise=0.21,
        train_ratio=0.85,
        hidden_layers=(16, 8),
        activation="relu",
        optimizer="SGD",
        learning_rate=0.015,
        epochs=120,
        batch_size=64,
        seed=42,
        feature_names=("x1", "x2", "sin_x1"),
        grid_size=64,
    )

    token = module._encode_share_config(config)
    decoded = module._decode_share_config(token)

    assert decoded == config
    assert module._config_from_query_params({"pytorch_playground": [token]}) == config
    assert module._decode_share_config("not-valid-base64") is None
    list_payload = module.base64.urlsafe_b64encode(b"[]").decode("ascii").rstrip("=")
    assert module._decode_share_config(list_payload) is None
    sanitized = module._config_from_payload(
        {
            "config": {
                "dataset": "invalid",
                "sample_count": 10_000,
                "noise": float("nan"),
                "hidden_layers": "8,wide",
                "activation": "unknown",
                "optimizer": "bad",
                "feature_names": ["x1", "missing", "x2"],
            }
        }
    )
    assert sanitized.dataset == "circles"
    assert sanitized.sample_count == 1000
    assert sanitized.noise == module.PlaygroundConfig().noise
    assert sanitized.hidden_layers == module.PlaygroundConfig().hidden_layers
    assert sanitized.activation == module.PlaygroundConfig().activation
    assert sanitized.optimizer == module.PlaygroundConfig().optimizer
    assert sanitized.feature_names == ("x1", "x2")
    assert module._preset_config(module.DEFAULT_PRESET).dataset == "circles"
    assert module._preset_config(module.CUSTOM_PRESET, config) == config
    assert "URL token" in module._preset_story(module.CUSTOM_PRESET, config)
    assert module._safe_key_fragment("Hard mode: spiral") == "hard_mode_spiral"
    assert module._config_state_payload(config)["hidden_layers"] == [16, 8]
    assert module._config_signature(config) == module._config_signature(decoded)


def test_pytorch_playground_training_state_stages_control_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    fake_st = SimpleNamespace(session_state={})
    monkeypatch.setattr(module, "st", fake_st)
    first = module.PlaygroundConfig(dataset="circles", seed=1)
    second = module.PlaygroundConfig(dataset="spiral", seed=2)

    trained, preset, pending = module._resolve_trained_config(
        first,
        module.DEFAULT_PRESET,
        train_requested=False,
    )
    assert trained == first
    assert preset == module.DEFAULT_PRESET
    assert pending is False

    trained, _preset, pending = module._resolve_trained_config(
        second,
        "Hard mode: spiral",
        train_requested=False,
    )
    assert trained == first
    assert pending is True

    trained, preset, pending = module._resolve_trained_config(
        second,
        "Hard mode: spiral",
        train_requested=True,
    )
    assert trained == second
    assert preset == "Hard mode: spiral"
    assert pending is False


def test_pytorch_playground_config_and_dataset_helper_edges(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()

    active_app = tmp_path / "active_app"
    active_app.mkdir()
    monkeypatch.setattr(sys, "argv", ["playground_ui.py", "--active-app", str(active_app)])
    assert module._resolve_active_app() == active_app.resolve()
    monkeypatch.setattr(sys, "argv", ["playground_ui.py", "--active-app", str(tmp_path / "missing")])
    assert module._resolve_active_app() is None
    monkeypatch.setattr(sys, "argv", ["playground_ui.py"])
    assert module._resolve_active_app() is None

    default = module.PlaygroundConfig()
    assert module._bounded_int("bad", default=5, minimum=1, maximum=10) == 5
    assert module._bounded_int(99, default=5, minimum=1, maximum=10) == 10
    assert module._bounded_float(None, default=0.2, minimum=0.0, maximum=1.0) == 0.2
    assert module._bounded_float(float("inf"), default=0.2, minimum=0.0, maximum=1.0) == 0.2
    assert module._bounded_float(-2.0, default=0.2, minimum=0.0, maximum=1.0) == 0.0
    assert module._coerce_hidden_layers([4, 2]) == (4, 2)
    assert module._coerce_hidden_layers(["bad"], (3,)) == (3,)
    assert module._coerce_hidden_layers(object(), (3,)) == (3,)
    assert module._coerce_feature_names("x1, missing, sin_x2") == ("x1", "sin_x2")
    assert module._coerce_feature_names(object(), ("x2",)) == ("x2",)
    assert module._config_from_payload({"config": []}) == default
    assert module._first_query_value([]) is None
    assert module._first_query_value(None) is None
    assert module._config_from_query_params({"config": module._encode_share_config(default)}) == default

    for dataset in ("circles", "spiral", "gaussian", "invalid"):
        frame = module._make_dataset(module.PlaygroundConfig(dataset=dataset, sample_count=35, seed=5))
        assert list(frame.columns) == ["x1", "x2", "target"]
        assert len(frame) == 35
        assert set(frame["target"].unique()) <= {0, 1}

    ndarray_features = module._feature_matrix(np.array([[1.0, 2.0], [3.0, 4.0]]), ())
    np.testing.assert_allclose(ndarray_features, np.array([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32))


def test_pytorch_playground_evidence_pack_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "torch", None)
    monkeypatch.setattr(module, "nn", None)
    config = module.PlaygroundConfig(sample_count=32, epochs=10, grid_size=12, seed=11)
    result = module._train_playground(config)
    loss_landscape = pd.DataFrame(
        [
            {
                "alpha": -0.1,
                "beta": 0.0,
                "train_loss": 0.7,
                "validation_loss": 0.8,
                "train_accuracy": 0.5,
                "validation_accuracy": 0.5,
                "is_center": False,
            },
            {
                "alpha": 0.0,
                "beta": 0.0,
                "train_loss": 0.5,
                "validation_loss": 0.6,
                "train_accuracy": 0.75,
                "validation_accuracy": 0.7,
                "is_center": True,
            },
        ],
        columns=module._empty_loss_landscape().columns,
    )
    result["loss_landscape"] = loss_landscape
    result["landscape_summary"] = module._loss_landscape_summary(loss_landscape)

    first = module._build_evidence_pack(config, result)
    second = module._build_evidence_pack(config, result)

    assert first == second
    archive_path = tmp_path / "pytorch_playground_evidence_test.zip"
    archive_path.write_bytes(first)
    with zipfile.ZipFile(archive_path, "r") as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert {
            "manifest.json",
            "config/playground_config.json",
            "data/samples.csv",
            "data/training_history.csv",
            "data/decision_grid.csv",
            "model/network_layers.csv",
            "model/hidden_activation_maps.csv",
            "model/loss_landscape.csv",
            "summary/run_summary.json",
        }.issubset(set(names))
        manifest = json.loads(archive.read("manifest.json").decode("utf-8"))
        sample_bytes = archive.read("data/samples.csv")
        landscape_bytes = archive.read("model/loss_landscape.csv")

    assert manifest["schema"] == module.EVIDENCE_SCHEMA
    assert manifest["app"] == "pytorch_playground_project"
    assert manifest["config_schema"] == module.CONFIG_SCHEMA
    assert manifest["row_counts"]["samples"] == 32
    assert manifest["row_counts"]["loss_landscape"] == 2
    assert manifest["landscape_summary"]["center_validation_loss"] == pytest.approx(0.6)
    assert manifest["artifacts"]["data/samples.csv"]["sha256"] == hashlib.sha256(sample_bytes).hexdigest()
    assert manifest["artifacts"]["model/loss_landscape.csv"]["sha256"] == hashlib.sha256(landscape_bytes).hexdigest()


def test_pytorch_playground_loss_landscape_summary_marks_center_and_best() -> None:
    module = _load_module()
    landscape = pd.DataFrame(
        [
            {"alpha": -0.5, "beta": 0.0, "train_loss": 0.8, "validation_loss": 0.9, "train_accuracy": 0.4, "validation_accuracy": 0.4, "is_center": False},
            {"alpha": 0.0, "beta": 0.0, "train_loss": 0.4, "validation_loss": 0.5, "train_accuracy": 0.8, "validation_accuracy": 0.75, "is_center": True},
            {"alpha": 0.5, "beta": 0.0, "train_loss": 0.3, "validation_loss": 0.45, "train_accuracy": 0.85, "validation_accuracy": 0.8, "is_center": False},
        ],
        columns=module._empty_loss_landscape().columns,
    )

    summary = module._loss_landscape_summary(landscape)

    assert summary["status"] == "ok"
    assert summary["points"] == 3
    assert summary["center_validation_loss"] == pytest.approx(0.5)
    assert summary["best_validation_loss"] == pytest.approx(0.45)
    assert summary["best_delta"] == pytest.approx(-0.05)
    assert summary["sharpness"] == pytest.approx(0.4)


def test_pytorch_playground_evidence_and_figure_helpers_cover_fallbacks(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()
    monkeypatch.setattr(module, "torch", None)
    monkeypatch.setattr(module, "nn", None)

    config = module.PlaygroundConfig(sample_count=20, grid_size=3, hidden_layers=())
    samples = pd.DataFrame({"x1": [-0.5, 0.5], "x2": [0.2, -0.2], "target": [0, 1]})
    irregular_grid = pd.DataFrame(
        {
            "x1": [-1.0, 0.0, 1.0],
            "x2": [-1.0, 0.0, 1.0],
            "probability": [0.1, 0.5, 0.9],
        }
    )
    history = pd.DataFrame(
        {
            "epoch": [0, 1],
            "train_loss": [0.8, 0.4],
            "validation_loss": [0.9, 0.5],
            "train_accuracy": [0.5, 0.8],
            "validation_accuracy": [0.4, 0.7],
        }
    )
    activation_maps = pd.DataFrame(
        {
            "layer": [1, 1, 1, 1],
            "neuron": [1, 1, 1, 1],
            "x1": [-1.0, 1.0, -1.0, 1.0],
            "x2": [-1.0, -1.0, 1.0, 1.0],
            "activation": [0.0, 0.5, 0.25, 1.0],
        }
    )
    loss_landscape = pd.DataFrame(
        {
            "alpha": [-0.5, 0.0, 0.5],
            "beta": [-0.5, 0.0, 0.5],
            "train_loss": [0.7, 0.5, 0.6],
            "validation_loss": [0.8, 0.45, 0.55],
            "train_accuracy": [0.5, 0.7, 0.6],
            "validation_accuracy": [0.4, 0.8, 0.7],
            "is_center": [False, True, False],
        }
    )
    layers = pd.DataFrame(
        [
            {
                "layer": 1,
                "kind": "hidden",
                "input_features": 2,
                "output_features": 3,
                "parameters": 9,
                "weight_mean": 0.1,
                "weight_std": 0.2,
                "weight_max_abs": 0.4,
                "bias_mean": 0.0,
                "bias_std": 0.1,
                "bias_max_abs": 0.2,
            }
        ]
    )
    result = {
        "samples": samples,
        "history": history,
        "grid": irregular_grid,
        "network_layers": layers,
        "activation_maps": activation_maps,
        "loss_landscape": loss_landscape,
        "summary": {"backend": "synthetic", "samples": 2, "features": 2},
    }

    assert module._activation_module.__name__ == "_activation_module"
    with pytest.raises(RuntimeError, match="PyTorch is not available"):
        module._activation_module("relu")
    with pytest.raises(RuntimeError, match="PyTorch is not available"):
        module._build_model(2, config)
    assert module._hidden_activation_maps(object(), config, np.ones((1, 2)), np.ones((1, 2))).empty
    assert module._array_stats(np.array([])) == {"mean": 0.0, "std": 0.0, "max_abs": 0.0}
    assert module._network_layers([]).empty
    assert module._empty_loss_landscape().empty
    assert module._normalized_landscape_resolution(4) == 5
    assert module._normalized_landscape_resolution(40) == 31
    assert module._loss_landscape_summary(module._empty_loss_landscape()) == {"status": "not_computed", "points": 0}
    landscape_summary = module._loss_landscape_summary(loss_landscape)
    assert landscape_summary["status"] == "ok"
    assert landscape_summary["best_validation_loss"] == 0.45
    assert module._loss_landscape(config)["status"] == "missing_torch"
    assert module._result_frame({}, "missing", samples) is samples
    assert module._json_safe({"bad": np.float64(float("nan")), "count": np.int64(3)}) == {"bad": None, "count": 3}
    assert module._format_percent(0.812) == "81%"
    assert module._confidence_score(irregular_grid) == pytest.approx(0.5333333333333333)
    assert module._confidence_score(pd.DataFrame(columns=["x1", "x2"])) == 0.0
    assert module._class_balance(samples) == "50/50% class split"
    assert module._class_balance(pd.DataFrame()) == "no samples"
    assert module._parameter_count(layers) == 9
    assert module._parameter_count(module._empty_network_layers()) == 0
    assert module._generalization_gap({"train_accuracy": 0.9, "validation_accuracy": 0.75}) == pytest.approx(0.15)

    x_axis, y_axis = module._grid_axes(irregular_grid, 5)
    assert len(x_axis) == 2
    assert len(y_axis) == 2
    assert module._grid_axes(pd.DataFrame(), 5)[0].size == 0
    assert len(module._decision_figure(samples, irregular_grid, 5).data) == 4
    assert len(module._decision_figure(samples, pd.DataFrame(columns=["x1", "x2", "probability"]), 5).data) == 2
    assert len(module._history_figure(history).data) == 4
    assert len(module._history_figure(pd.DataFrame()).data) == 0
    assert len(module._activation_figure(activation_maps, 1, 1).data) == 1
    assert len(module._activation_figure(activation_maps, 2, 1).data) == 0
    assert len(module._network_figure(layers).data) == 2
    assert len(module._network_figure(module._empty_network_layers()).data) == 0
    assert len(module._loss_landscape_figure(loss_landscape).data) == 3
    assert len(module._loss_landscape_figure(module._empty_loss_landscape()).data) == 0

    manifest = module._build_evidence_manifest(config, result)
    assert manifest["row_counts"]["network_layers"] == 1
    assert manifest["row_counts"]["loss_landscape"] == 3
    assert set(module._evidence_artifact_files(config, {"summary": {}})) >= {
        "data/samples.csv",
        "model/network_layers.csv",
        "model/loss_landscape.csv",
    }
    assert module._cached_train(module.asdict(config))["status"] == "missing_torch"
    assert module._cached_loss_landscape(module.asdict(config), 4, 0.5)["status"] == "missing_torch"


def test_pytorch_playground_fake_nn_covers_model_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    class FakeTensor:
        def __init__(self, values):
            self._values = np.asarray(values, dtype=float)

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self._values

    class FakeLinear:
        def __init__(self, in_features: int, out_features: int, *, bias: bool = True):
            self.in_features = in_features
            self.out_features = out_features
            self.weight = FakeTensor(np.full((out_features, in_features), 0.25))
            self.bias = FakeTensor(np.linspace(-0.1, 0.1, out_features)) if bias else None

    class FakeSequential(list):
        def __init__(self, *layers):
            super().__init__(layers)

    fake_nn = SimpleNamespace(
        Linear=FakeLinear,
        ReLU=lambda: SimpleNamespace(kind="relu"),
        Sigmoid=lambda: SimpleNamespace(kind="sigmoid"),
        Identity=lambda: SimpleNamespace(kind="identity"),
        Tanh=lambda: SimpleNamespace(kind="tanh"),
        Sequential=FakeSequential,
    )
    monkeypatch.setattr(module, "nn", fake_nn)

    assert module._activation_module("relu").kind == "relu"
    assert module._activation_module("sigmoid").kind == "sigmoid"
    assert module._activation_module("identity").kind == "identity"
    assert module._activation_module("other").kind == "tanh"

    model = module._build_model(
        3,
        module.PlaygroundConfig(hidden_layers=(4, 2), activation="identity"),
    )
    assert [type(layer).__name__ for layer in model].count("FakeLinear") == 3
    layers = module._network_layers(model)
    assert layers["kind"].tolist() == ["hidden", "hidden", "output"]
    assert layers["parameters"].tolist() == [16, 10, 6]

    no_bias = module._network_layers([FakeLinear(2, 1, bias=False)])
    assert no_bias.iloc[0]["bias_max_abs"] == 0.0
    assert module._grid_points(module.PlaygroundConfig(grid_size=4)).shape == (144, 2)


def test_pytorch_playground_fake_torch_covers_activation_and_grid_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()

    class FakeTorchTensor:
        def __init__(self, values):
            self.values = np.asarray(values, dtype=float)

        def __getitem__(self, key):
            return FakeTorchTensor(self.values[key])

        def detach(self):
            return self

        def cpu(self):
            return self

        def numpy(self):
            return self.values

    class FakeNoGrad:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class FakeTorch:
        float32 = "float32"
        long = "long"

        @staticmethod
        def tensor(values, dtype=None):
            if dtype == FakeTorch.long:
                return np.asarray(values, dtype=np.int64)
            return FakeTorchTensor(values)

        @staticmethod
        def no_grad():
            return FakeNoGrad()

        @staticmethod
        def softmax(logits, dim=1):
            values = logits.values
            shifted = values - values.max(axis=dim, keepdims=True)
            exp = np.exp(shifted)
            return FakeTorchTensor(exp / exp.sum(axis=dim, keepdims=True))

    class FakeLinear:
        def __init__(self, in_features: int, out_features: int):
            self.in_features = in_features
            self.out_features = out_features

        def __call__(self, values):
            row_count = values.values.shape[0]
            columns = [
                values.values[:, index % values.values.shape[1]] + (index + 1) * 0.1
                for index in range(self.out_features)
            ]
            return FakeTorchTensor(np.column_stack(columns).reshape(row_count, self.out_features))

    class FakeActivation:
        def __call__(self, values):
            return values

    class FakeModel(list):
        def eval(self):
            return None

        def __call__(self, values):
            for layer in self:
                values = layer(values)
            return values

    monkeypatch.setattr(
        module,
        "nn",
        SimpleNamespace(Linear=FakeLinear),
    )
    monkeypatch.setattr(module, "torch", FakeTorch)

    config = module.PlaygroundConfig(
        sample_count=20,
        train_ratio=0.8,
        hidden_layers=(3,),
        feature_names=("x1", "x2"),
        grid_size=12,
    )
    training_data = module._prepare_training_data(config)
    assert training_data["x_train"].values.shape[1] == 2
    assert training_data["y_train"].dtype == np.int64

    model = FakeModel([FakeLinear(2, 3), FakeActivation(), FakeLinear(3, 2)])
    activation_maps = module._hidden_activation_maps(
        model,
        config,
        training_data["mean"],
        training_data["std"],
        max_neurons=2,
    )
    assert activation_maps.shape[0] == 12 * 12 * 2
    assert sorted(activation_maps["neuron"].unique().tolist()) == [1, 2]

    decision_grid = module._decision_grid(model, config, training_data["mean"], training_data["std"])
    assert decision_grid.shape[0] == 12 * 12
    assert decision_grid["probability"].between(0.0, 1.0).all()


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
    assert not result["network_layers"].empty
    assert not result["activation_maps"].empty
    assert sorted(result["activation_maps"]["layer"].unique().tolist()) == [1]
    assert 0.0 <= result["summary"]["validation_accuracy"] <= 1.0
    assert result["summary"]["backend"] == "torch"

    landscape_result = module._loss_landscape(config, resolution=5, span=0.2)
    assert landscape_result["status"] == "ok"
    assert landscape_result["loss_landscape"].shape[0] == 25
    assert landscape_result["loss_landscape"]["is_center"].sum() == 1
    assert landscape_result["landscape_summary"]["points"] == 25


def test_pytorch_playground_app_args_convert_to_playground_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    app_args = importlib.import_module("pytorch_playground.app_args")

    args = app_args.PytorchPlaygroundArgs(
        hidden_layers="4, 2",
        feature_names="x1, missing, sin_x2",
        sample_count=96,
    )
    config = app_args.to_playground_config(args)

    assert config.hidden_layers == (4, 2)
    assert config.feature_names == ("x1", "sin_x2")
    assert config.sample_count == 96


def test_pytorch_playground_distribution_marks_extra_workers_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    manager_module = importlib.import_module("pytorch_playground.pytorch_playground")

    manager = manager_module.PytorchPlayground.__new__(manager_module.PytorchPlayground)
    work_plan, metadata, id_name, count_name, label = manager.build_distribution(3)

    assert work_plan == [[["pytorch_playground"]], [], []]
    assert metadata == [[{"run": "pytorch_playground", "work_items": 1}], [], []]
    assert (id_name, count_name, label) == ("run", "work_items", "items")


def test_pytorch_playground_analysis_artifact_dir_uses_env_fallback(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    manager_module = importlib.import_module("pytorch_playground.pytorch_playground")

    manager = manager_module.PytorchPlayground.__new__(manager_module.PytorchPlayground)
    manager.env = SimpleNamespace(AGILAB_EXPORT_ABS=tmp_path, app="custom_playground")

    assert manager.analysis_artifact_dir == tmp_path / "custom_playground" / "pytorch_playground"


def test_pytorch_playground_app_settings_default_to_single_worker() -> None:
    import tomllib

    settings = tomllib.loads((PROJECT_PATH / "src" / "app_settings.toml").read_text(encoding="utf-8"))

    assert settings["cluster"]["workers"] == {"127.0.0.1": 1}
    assert settings["pages"]["view_module"] == ["view_app_ui"]
    assert settings["pages"]["view_app_ui"]["entrypoint"] == "pytorch_playground/playground_ui.py"
    assert settings["pages"]["view_app_ui"]["title"] == "PyTorch Playground"


def test_pytorch_playground_hides_distribution_preview_by_contract() -> None:
    import tomllib

    source_pyproject = tomllib.loads((PROJECT_PATH / "pyproject.toml").read_text(encoding="utf-8"))
    payload_pyproject = tomllib.loads((PACKAGE_PROJECT_PATH / "pyproject.toml").read_text(encoding="utf-8"))

    assert source_pyproject["tool"]["agilab"]["app"]["distribution_preview"] is False
    assert payload_pyproject["tool"]["agilab"]["app"]["distribution_preview"] is False


def test_pytorch_playground_app_args_form_uses_project_scoped_static_json() -> None:
    source = (PROJECT_PATH / "src" / "app_args_form.py").read_text(encoding="utf-8")

    assert "render_form(" not in source
    assert "APP_FORM_ID" in source
    assert "def _field_key" in source
    assert "key=key" in source
    assert "st.json(" not in source
    assert ".multiselect(" not in source


def test_pytorch_playground_source_and_packaged_payload_stay_aligned() -> None:
    source_root = PROJECT_PATH / "src"
    payload_root = PACKAGE_PROJECT_PATH / "src"
    source_files = _runtime_payload_files(source_root)
    payload_files = _runtime_payload_files(payload_root)

    assert source_files == payload_files

    mismatches = [
        str(relative)
        for relative in sorted(source_files - EXPECTED_SOURCE_PAYLOAD_DIFFS)
        if (source_root / relative).read_bytes() != (payload_root / relative).read_bytes()
    ]
    assert mismatches == []

    source_worker_manifest = (source_root / "pytorch_playground_worker" / "pyproject.toml").read_text(encoding="utf-8")
    payload_worker_manifest = (payload_root / "pytorch_playground_worker" / "pyproject.toml").read_text(encoding="utf-8")
    assert "[tool.uv.sources]" in source_worker_manifest
    assert "[tool.uv.sources]" not in payload_worker_manifest


def test_pytorch_playground_worker_exports_evidence_without_torch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    core_module = importlib.import_module("pytorch_playground.core")
    worker_module = importlib.import_module("pytorch_playground_worker.pytorch_playground_worker")
    args_module = importlib.import_module("pytorch_playground.app_args")
    monkeypatch.setattr(core_module, "torch", None)
    monkeypatch.setattr(core_module, "nn", None)

    worker = worker_module.PytorchPlaygroundWorker.__new__(worker_module.PytorchPlaygroundWorker)
    worker.args = args_module.PytorchPlaygroundArgs(
        data_out=tmp_path / "out",
        sample_count=64,
        epochs=10,
        grid_size=12,
        reset_target=True,
    ).model_dump(mode="json")
    worker.env = SimpleNamespace(target="pytorch_playground_project", AGILAB_EXPORT_ABS=tmp_path / "export")
    worker._worker_id = 0

    worker.start()
    summary = worker.work_pool("pytorch_playground")

    assert summary.iloc[0]["backend"] == "missing"
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["app"] == "pytorch_playground_project"
    assert (tmp_path / "out" / "pytorch_playground_evidence.zip").is_file()
    assert (tmp_path / "export" / "pytorch_playground_project" / "pytorch_playground" / "manifest.json").is_file()


def test_pytorch_playground_worker_exports_real_torch_evidence_when_available(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.syspath_prepend(str(PROJECT_SRC.resolve()))
    core_module = importlib.import_module("pytorch_playground.core")
    if core_module.torch is None:
        pytest.skip("torch is not installed in this validation environment")

    worker_module = importlib.import_module("pytorch_playground_worker.pytorch_playground_worker")
    args_module = importlib.import_module("pytorch_playground.app_args")

    worker = worker_module.PytorchPlaygroundWorker.__new__(worker_module.PytorchPlaygroundWorker)
    worker.args = args_module.PytorchPlaygroundArgs(
        data_out=tmp_path / "out",
        dataset="gaussian",
        sample_count=64,
        hidden_layers="4",
        feature_names="x1,x2",
        epochs=10,
        batch_size=16,
        grid_size=12,
        compute_loss_landscape=True,
        landscape_resolution=5,
        landscape_span=0.2,
        reset_target=True,
    ).model_dump(mode="json")
    worker.env = SimpleNamespace(target="pytorch_playground_project", AGILAB_EXPORT_ABS=tmp_path / "export")
    worker._worker_id = 0

    worker.start()
    summary = worker.work_pool("pytorch_playground")

    assert summary.iloc[0]["backend"] == "torch"
    assert summary.iloc[0]["loss_landscape_points"] == 25
    manifest = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["backend"] == "torch"
    assert manifest["row_counts"]["training_history"] >= 2
    assert manifest["row_counts"]["decision_grid"] == 144
    assert manifest["row_counts"]["loss_landscape"] == 25
    assert manifest["torch_version"]
    archive_path = tmp_path / "out" / "pytorch_playground_evidence.zip"
    with zipfile.ZipFile(archive_path, "r") as archive:
        assert "manifest.json" in archive.namelist()
        assert json.loads(archive.read("manifest.json").decode("utf-8"))["backend"] == "torch"


def test_pytorch_playground_main_covers_empty_and_error_ui_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_module()

    class StopRender(RuntimeError):
        pass

    class FakeContext:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def metric(self, *_args, **_kwargs):
            return None

    class FakeStreamlit:
        def __init__(self, *, hidden_raw: str = "8,8", checkbox: bool = False):
            self.query_params = {}
            self.session_state: dict[str, object] = {}
            self.sidebar = FakeContext()
            self.hidden_raw = hidden_raw
            self.checkbox_value = checkbox
            self.errors: list[str] = []
            self.infos: list[str] = []
            self.warnings: list[str] = []
            self.downloads: list[bytes] = []
            self.code_payloads: list[tuple[str, str | None]] = []

        def set_page_config(self, **_kwargs):
            return None

        def title(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def markdown(self, *_args, **_kwargs):
            return None

        def error(self, message, **_kwargs):
            self.errors.append(str(message))

        def warning(self, message, **_kwargs):
            self.warnings.append(str(message))

        def stop(self):
            raise StopRender()

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [FakeContext() for _ in range(count)]

        def tabs(self, labels):
            return [FakeContext() for _ in labels]

        def selectbox(self, _label, options, index=0, **_kwargs):
            return list(options)[index]

        def slider(self, _label, _min, _max, value, **_kwargs):
            return value

        def multiselect(self, _label, _options, default=None, **_kwargs):
            return list(default or [])

        def text_input(self, _label, value="", **_kwargs):
            return self.hidden_raw

        def number_input(self, _label, value=0, **_kwargs):
            return value

        def checkbox(self, *_args, **_kwargs):
            return self.checkbox_value

        def button(self, *_args, **_kwargs):
            return False

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def info(self, message, **_kwargs):
            self.infos.append(str(message))

        def metric(self, *_args, **_kwargs):
            return None

        def download_button(self, _label, data, **_kwargs):
            self.downloads.append(data)
            return False

        def code(self, body, **kwargs):
            self.code_payloads.append((str(body), kwargs.get("language")))
            return None

        def json(self, payload, **_kwargs):
            raise AssertionError(f"st.json should not be used by PyTorch Playground: {payload!r}")

    def empty_result(status: str = "ok") -> dict[str, object]:
        return {
            "status": status,
            "detail": "missing torch detail",
            "samples": pd.DataFrame({"x1": [-0.2, 0.2], "x2": [0.1, -0.1], "target": [0, 1]}),
            "history": pd.DataFrame(
                columns=["epoch", "train_loss", "validation_loss", "train_accuracy", "validation_accuracy"]
            ),
            "grid": pd.DataFrame(columns=["x1", "x2", "probability"]),
            "network_layers": module._empty_network_layers(),
            "activation_maps": module._empty_activation_maps(),
            "summary": {"backend": status, "samples": 2, "features": 2},
        }

    invalid_st = FakeStreamlit(hidden_raw="8,wide")
    monkeypatch.setattr(module, "st", invalid_st)
    monkeypatch.setattr(module, "render_logo", lambda: None)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: None)
    monkeypatch.setattr(module, "_cached_train", lambda _payload: empty_result())
    with pytest.raises(StopRender):
        module.main()
    assert invalid_st.errors == ["Hidden layer width must be an integer: wide"]

    ok_st = FakeStreamlit(checkbox=False)
    monkeypatch.setattr(module, "st", ok_st)
    monkeypatch.setattr(module, "_cached_train", lambda _payload: empty_result())
    module.main()
    assert any("Hidden activation maps" in message for message in ok_st.infos)
    assert any("Enable computation" in message for message in ok_st.infos)
    manifest = next(json.loads(body) for body, language in ok_st.code_payloads if language == "json")
    assert manifest["row_counts"]["loss_landscape"] == 0

    missing_st = FakeStreamlit(checkbox=True)
    monkeypatch.setattr(module, "st", missing_st)
    monkeypatch.setattr(module, "_cached_train", lambda _payload: empty_result("missing_torch"))
    module.main()
    assert missing_st.errors == ["missing torch detail"]
    assert any("Loss landscape is available" in message for message in missing_st.infos)


def test_pytorch_playground_main_renders_with_fake_streamlit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    module = _load_module()

    class FakeContext:
        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

        def metric(self, *_args, **_kwargs):
            return None

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def selectbox(self, _label, options, index=0, **_kwargs):
            return list(options)[index]

    class FakeStreamlit:
        def __init__(self):
            self.query_params = {}
            self.session_state: dict[str, object] = {}
            self.sidebar = FakeContext()
            self.downloads: list[bytes] = []
            self.code_payloads: list[tuple[str, str | None]] = []

        def set_page_config(self, **_kwargs):
            return None

        def title(self, *_args, **_kwargs):
            return None

        def caption(self, *_args, **_kwargs):
            return None

        def markdown(self, *_args, **_kwargs):
            return None

        def error(self, *_args, **_kwargs):
            return None

        def warning(self, *_args, **_kwargs):
            return None

        def stop(self):
            raise AssertionError("stop should not be called")

        def columns(self, spec):
            count = spec if isinstance(spec, int) else len(spec)
            return [FakeContext() for _ in range(count)]

        def tabs(self, labels):
            return [FakeContext() for _ in labels]

        def selectbox(self, _label, options, index=0, **_kwargs):
            return list(options)[index]

        def slider(self, _label, _min, _max, value, **_kwargs):
            return value

        def multiselect(self, _label, _options, default=None, **_kwargs):
            return list(default or [])

        def text_input(self, _label, value="", **_kwargs):
            return value

        def number_input(self, _label, value=0, **_kwargs):
            return value

        def checkbox(self, *_args, **_kwargs):
            return True

        def button(self, *_args, **_kwargs):
            return False

        def plotly_chart(self, *_args, **_kwargs):
            return None

        def dataframe(self, *_args, **_kwargs):
            return None

        def info(self, *_args, **_kwargs):
            return None

        def metric(self, *_args, **_kwargs):
            return None

        def download_button(self, _label, data, **_kwargs):
            self.downloads.append(data)
            return False

        def code(self, body, **kwargs):
            self.code_payloads.append((str(body), kwargs.get("language")))
            return None

        def json(self, payload, **_kwargs):
            raise AssertionError(f"st.json should not be used by PyTorch Playground: {payload!r}")

    fake_st = FakeStreamlit()
    config = module.PlaygroundConfig(sample_count=64, grid_size=12, hidden_layers=(2,))
    samples = module._make_dataset(config)
    grid = pd.DataFrame(
        {
            "x1": [-1.0, 1.0, -1.0, 1.0],
            "x2": [-1.0, -1.0, 1.0, 1.0],
            "probability": [0.1, 0.9, 0.2, 0.8],
        }
    )
    history = pd.DataFrame(
        {
            "epoch": [0],
            "train_loss": [0.5],
            "validation_loss": [0.6],
            "train_accuracy": [0.7],
            "validation_accuracy": [0.8],
        }
    )
    layers = pd.DataFrame(
        [
            {
                "layer": 1,
                "kind": "hidden",
                "input_features": 2,
                "output_features": 2,
                "parameters": 6,
                "weight_mean": 0.0,
                "weight_std": 0.1,
                "weight_max_abs": 0.3,
                "bias_mean": 0.0,
                "bias_std": 0.1,
                "bias_max_abs": 0.2,
            }
        ]
    )
    activation_maps = pd.DataFrame(
        {
            "layer": [1, 1, 1, 1],
            "neuron": [1, 1, 1, 1],
            "x1": [-1.0, 1.0, -1.0, 1.0],
            "x2": [-1.0, -1.0, 1.0, 1.0],
            "activation": [0.0, 1.0, 0.4, 0.8],
        }
    )
    loss_landscape = pd.DataFrame(
        {
            "alpha": [-0.25, 0.0, 0.25],
            "beta": [-0.25, 0.0, 0.25],
            "train_loss": [0.6, 0.5, 0.7],
            "validation_loss": [0.65, 0.45, 0.75],
            "train_accuracy": [0.6, 0.7, 0.5],
            "validation_accuracy": [0.55, 0.8, 0.45],
            "is_center": [False, True, False],
        }
    )
    result = {
        "status": "ok",
        "detail": "",
        "samples": samples,
        "history": history,
        "grid": grid,
        "network_layers": layers,
        "activation_maps": activation_maps,
        "summary": {"backend": "synthetic", "samples": len(samples), "features": 2},
    }

    monkeypatch.setattr(module, "st", fake_st)
    monkeypatch.setattr(module, "render_logo", lambda: None)
    monkeypatch.setattr(module, "_resolve_active_app", lambda: tmp_path)
    monkeypatch.setattr(module, "_cached_train", lambda _payload: result)
    monkeypatch.setattr(
        module,
        "_cached_loss_landscape",
        lambda _payload, _resolution, _span: {
            "status": "ok",
            "detail": "",
            "loss_landscape": loss_landscape,
            "landscape_summary": module._loss_landscape_summary(loss_landscape),
        },
    )

    module.main()

    assert fake_st.downloads
    manifest = next(json.loads(body) for body, language in fake_st.code_payloads if language == "json")
    assert manifest["schema"] == module.EVIDENCE_SCHEMA


def test_pytorch_playground_app_provider_and_package_docs(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("agi_app_pytorch_playground_init_test_module", INIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    source_root = INIT_PATH.resolve().parents[4] / "apps" / "builtin" / "pytorch_playground_project"
    assert module.project_root() == source_root.resolve()

    fake_package_root = (
        tmp_path
        / ".venv"
        / "lib"
        / "python3.13"
        / "site-packages"
        / "agi_app_pytorch_playground"
    )
    fake_payload = fake_package_root / "project" / "pytorch_playground_project"
    fake_payload.mkdir(parents=True, exist_ok=True)
    original_file = module.__file__
    try:
        module.__file__ = str(fake_package_root / "__init__.py")
        assert module.project_root() == fake_payload
    finally:
        module.__file__ = original_file

    assert module.metadata()["project"] == "pytorch_playground_project"
    readme = README_PATH.read_text(encoding="utf-8")
    assert "pytorch_playground_project" in readme
    assert "agi-app-pytorch-playground" in readme
    assert "generic app-agnostic analysis page" in readme
