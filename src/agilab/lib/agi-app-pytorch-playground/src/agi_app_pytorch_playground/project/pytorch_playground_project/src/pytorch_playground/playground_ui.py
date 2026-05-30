# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import html
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
try:  # pragma: no cover - optional in headless worker/test environments
    import plotly.graph_objects as go
except Exception:  # pragma: no cover - app UI installs plotly, workers do not need it
    go = None  # type: ignore[assignment]

try:  # pragma: no cover - optional in headless worker/test environments
    import streamlit as st
except Exception:  # pragma: no cover - workers import evidence helpers without Streamlit
    class _StreamlitStub:
        query_params: dict[str, object] = {}
        session_state: dict[str, object] = {}

        @staticmethod
        def cache_data(*_args, **_kwargs):
            def _decorator(func):
                return func

            return _decorator

        def __getattr__(self, name: str):
            raise RuntimeError(f"Streamlit is required to render the PyTorch playground UI: {name}")

    st = _StreamlitStub()  # type: ignore[assignment]


def _prepend_sys_path(path: Path) -> None:
    entry = str(path)
    sys.path[:] = [existing for existing in sys.path if existing != entry]
    sys.path.insert(0, entry)


def _ensure_repo_on_path() -> None:
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "agilab"
        if candidate.is_dir():
            src_root = candidate.parent
            repo_root = src_root.parent
            for entry in (str(src_root), str(repo_root)):
                if entry not in sys.path:
                    sys.path.insert(0, entry)
            break


_ensure_repo_on_path()

_APP_SRC = Path(__file__).resolve().parents[1]
_prepend_sys_path(_APP_SRC)

try:  # noqa: E402
    import pytorch_playground.core as _playground_core
    from pytorch_playground.core import (
        ACTIVATIONS,
        DATASETS,
        DEFAULT_FEATURES,
        DEFAULT_PRESET,
        FEATURES,
        OPTIMIZERS,
        PLAYGROUND_PRESETS,
        REGULARIZATIONS,
        SHARED_CONFIG_SIGNATURE_STATE_KEY,
        TRAINED_CONFIG_STATE_KEY,
        TRAINED_PRESET_STATE_KEY,
        PlaygroundConfig,
        _build_evidence_manifest,
        _build_evidence_pack,
        _config_from_payload,
        _config_from_query_params,
        _config_signature,
        _config_state_payload,
        _empty_activation_maps,
        _empty_boundary_snapshots,
        _empty_loss_landscape,
        _empty_network_layers,
        _encode_share_config,
        _json_safe,
        _loss_landscape,
        _loss_landscape_summary,
        _make_dataset,
        _parse_hidden_layers,
        _plotly_unavailable_figure,
        _preset_config,
        _preset_story,
        _resolve_active_app,
        _result_frame,
        _safe_key_fragment,
        _train_playground,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution fallback
    import core as _playground_core
    from core import (
        ACTIVATIONS,
        DATASETS,
        DEFAULT_FEATURES,
        DEFAULT_PRESET,
        FEATURES,
        OPTIMIZERS,
        PLAYGROUND_PRESETS,
        REGULARIZATIONS,
        SHARED_CONFIG_SIGNATURE_STATE_KEY,
        TRAINED_CONFIG_STATE_KEY,
        TRAINED_PRESET_STATE_KEY,
        PlaygroundConfig,
        _build_evidence_manifest,
        _build_evidence_pack,
        _config_from_payload,
        _config_from_query_params,
        _config_signature,
        _config_state_payload,
        _empty_activation_maps,
        _empty_boundary_snapshots,
        _empty_loss_landscape,
        _empty_network_layers,
        _encode_share_config,
        _json_safe,
        _loss_landscape,
        _loss_landscape_summary,
        _make_dataset,
        _parse_hidden_layers,
        _plotly_unavailable_figure,
        _preset_config,
        _preset_story,
        _resolve_active_app,
        _result_frame,
        _safe_key_fragment,
        _train_playground,
    )

try:  # noqa: E402
    from agi_gui.pagelib import render_logo
except Exception:  # pragma: no cover - headless worker/test environments
    def render_logo() -> None:
        return None


torch = _playground_core.torch
nn = _playground_core.nn


def _call_core(name: str, *args, **kwargs):
    previous_torch = _playground_core.torch
    previous_nn = _playground_core.nn
    _playground_core.torch = torch
    _playground_core.nn = nn
    try:
        return getattr(_playground_core, name)(*args, **kwargs)
    finally:
        _playground_core.torch = previous_torch
        _playground_core.nn = previous_nn


def _activation_module(name: str):
    return _call_core("_activation_module", name)


def _build_model(input_dim: int, config: PlaygroundConfig):
    return _call_core("_build_model", input_dim, config)


def _hidden_activation_maps(*args, **kwargs) -> pd.DataFrame:
    return _call_core("_hidden_activation_maps", *args, **kwargs)


def _network_layers(model) -> pd.DataFrame:
    return _call_core("_network_layers", model)


def _prepare_training_data(config: PlaygroundConfig) -> dict[str, Any]:
    return _call_core("_prepare_training_data", config)


def _decision_grid(*args, **kwargs) -> pd.DataFrame:
    return _call_core("_decision_grid", *args, **kwargs)


def _train_playground(config: PlaygroundConfig) -> dict[str, Any]:
    return _call_core("_train_playground", config)


def _loss_landscape(config: PlaygroundConfig, *, resolution: int = 21, span: float = 0.75) -> dict[str, Any]:
    return _call_core("_loss_landscape", config, resolution=resolution, span=span)


def __getattr__(name: str) -> Any:
    try:
        return getattr(_playground_core, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc


PAGE_TITLE = "PyTorch Playground"


_ISOLATED_CORE_RUNNER = r"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from pytorch_playground.core import PlaygroundConfig, _loss_landscape, _train_playground

_DATAFRAME_IPC_TYPE = "agilab.pytorch_playground.dataframe.v1"


def _ipc_encode(value):
    if isinstance(value, pd.DataFrame):
        return {
            "__type__": _DATAFRAME_IPC_TYPE,
            "columns": [str(column) for column in value.columns],
            "records": value.to_dict(orient="records"),
        }
    if isinstance(value, dict):
        return {str(key): _ipc_encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ipc_encode(item) for item in value]
    try:
        import numpy as np
    except Exception:
        np = None
    if np is not None:
        if isinstance(value, np.integer):
            return int(value)
        if isinstance(value, np.floating):
            number = float(value)
            return number if np.isfinite(number) else None
        if isinstance(value, np.ndarray):
            return _ipc_encode(value.tolist())
    if isinstance(value, float):
        try:
            import math

            return value if math.isfinite(value) else None
        except Exception:
            return value
    return value


def _write_response(output_path: Path, output: dict[str, object]) -> None:
    output_path.write_text(json.dumps(_ipc_encode(output), sort_keys=True) + "\n", encoding="utf-8")


def _config_from_payload(payload: dict[str, object]) -> PlaygroundConfig:
    return PlaygroundConfig(
        dataset=str(payload["dataset"]),
        sample_count=int(payload["sample_count"]),
        noise=float(payload["noise"]),
        train_ratio=float(payload["train_ratio"]),
        hidden_layers=tuple(int(value) for value in payload["hidden_layers"]),
        activation=str(payload["activation"]),
        optimizer=str(payload["optimizer"]),
        regularization=str(payload.get("regularization", "None")),
        regularization_rate=float(payload.get("regularization_rate", 0.0)),
        learning_rate=float(payload["learning_rate"]),
        epochs=int(payload["epochs"]),
        batch_size=int(payload["batch_size"]),
        seed=int(payload["seed"]),
        feature_names=tuple(str(value) for value in payload["feature_names"]),
        grid_size=int(payload["grid_size"]),
    )


input_path = Path(sys.argv[1])
output_path = Path(sys.argv[2])
try:
    request = json.loads(input_path.read_text(encoding="utf-8"))
    config = _config_from_payload(request["config"])
    if request["action"] == "train":
        result = _train_playground(config)
    elif request["action"] == "loss_landscape":
        result = _loss_landscape(
            config,
            resolution=int(request["resolution"]),
            span=float(request["span"]),
        )
    else:
        raise ValueError(f"Unknown isolated playground action: {request['action']}")
except BaseException as exc:
    output = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}
else:
    output = {"ok": True, "result": result}

try:
    _write_response(output_path, output)
except BaseException as exc:
    _write_response(output_path, {"ok": False, "error_type": type(exc).__name__, "error": str(exc)})
"""


_DATAFRAME_IPC_TYPE = "agilab.pytorch_playground.dataframe.v1"


def _ipc_encode(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        return {
            "__type__": _DATAFRAME_IPC_TYPE,
            "columns": [str(column) for column in value.columns],
            "records": _json_safe(value.to_dict(orient="records")),
        }
    if isinstance(value, Mapping):
        return {str(key): _ipc_encode(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_ipc_encode(item) for item in value]
    if isinstance(value, np.ndarray):
        return _ipc_encode(value.tolist())
    return _json_safe(value)


def _ipc_decode(value: Any) -> Any:
    if isinstance(value, Mapping):
        if value.get("__type__") == _DATAFRAME_IPC_TYPE:
            columns = value.get("columns", [])
            records = value.get("records", [])
            if not isinstance(columns, list) or not all(isinstance(column, str) for column in columns):
                raise ValueError("invalid dataframe columns in isolated runner response")
            if not isinstance(records, list):
                raise ValueError("invalid dataframe records in isolated runner response")
            return pd.DataFrame(records, columns=columns)
        return {str(key): _ipc_decode(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_ipc_decode(item) for item in value]
    return value


def _config_from_cache_payload(payload: Mapping[str, Any]) -> PlaygroundConfig:
    return PlaygroundConfig(
        dataset=str(payload["dataset"]),
        sample_count=int(payload["sample_count"]),
        noise=float(payload["noise"]),
        train_ratio=float(payload["train_ratio"]),
        hidden_layers=tuple(int(value) for value in payload["hidden_layers"]),
        activation=str(payload["activation"]),
        optimizer=str(payload["optimizer"]),
        regularization=str(payload.get("regularization", "None")),
        regularization_rate=float(payload.get("regularization_rate", 0.0)),
        learning_rate=float(payload["learning_rate"]),
        epochs=int(payload["epochs"]),
        batch_size=int(payload["batch_size"]),
        seed=int(payload["seed"]),
        feature_names=tuple(str(value) for value in payload["feature_names"]),
        grid_size=int(payload["grid_size"]),
    )


def _streamlit_script_context_active() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
    except Exception:
        return False
    return get_script_run_ctx(suppress_warning=True) is not None


def _use_isolated_torch_training() -> bool:
    return torch is not None and nn is not None and _streamlit_script_context_active()


def _tail_diagnostic(text: str, *, line_limit: int = 8, char_limit: int = 1600) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines[-line_limit:])[:char_limit]


def _training_error_result(config: PlaygroundConfig, detail: str) -> dict[str, Any]:
    samples = _make_dataset(config)
    return {
        "status": "error",
        "detail": detail,
        "samples": samples,
        "history": pd.DataFrame(columns=["epoch", "train_loss", "validation_loss", "train_accuracy", "validation_accuracy"]),
        "grid": pd.DataFrame(columns=["x1", "x2", "probability"]),
        "network_layers": _empty_network_layers(),
        "activation_maps": _empty_activation_maps(),
        "summary": {
            "backend": "error",
            "samples": int(len(samples)),
            "features": int(len(config.feature_names)),
        },
    }


def _loss_landscape_error_result(detail: str) -> dict[str, Any]:
    return {
        "status": "error",
        "detail": detail,
        "loss_landscape": _empty_loss_landscape(),
        "landscape_summary": {"status": "error", "points": 0},
    }


def _format_isolated_runner_failure(
    action: str,
    *,
    returncode: int | None = None,
    error: str = "",
    stderr: str = "",
) -> str:
    detail = f"PyTorch {action.replace('_', ' ')} failed in the isolated Streamlit UI runner"
    if returncode is not None:
        detail = f"{detail} (exit code {returncode})"
    diagnostics = _tail_diagnostic("\n".join(part for part in (error, stderr) if part))
    if diagnostics:
        detail = f"{detail}: {diagnostics}"
    else:
        detail = f"{detail}."
    return detail


def _run_core_in_subprocess(
    action: str,
    config: PlaygroundConfig,
    *,
    resolution: int | None = None,
    span: float | None = None,
) -> dict[str, Any]:
    request = {
        "action": action,
        "config": asdict(config),
        "resolution": int(resolution or 0),
        "span": float(span or 0.0),
    }
    with tempfile.TemporaryDirectory(prefix="agilab-pytorch-playground-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / "request.json"
        output_path = tmp_path / "response.json"
        input_path.write_text(json.dumps(_ipc_encode(request), sort_keys=True) + "\n", encoding="utf-8")
        env = os.environ.copy()
        project_src = str(_APP_SRC)
        python_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = project_src if not python_path else os.pathsep.join((project_src, python_path))
        env.setdefault("PYTHONFAULTHANDLER", "1")
        try:
            completed = subprocess.run(
                [sys.executable, "-c", _ISOLATED_CORE_RUNNER, str(input_path), str(output_path)],
                cwd=str(_APP_SRC.parent),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            detail = _format_isolated_runner_failure(action, error=f"timed out after {exc.timeout} seconds")
            if action == "train":
                return _training_error_result(config, detail)
            return _loss_landscape_error_result(detail)

        if completed.returncode != 0 or not output_path.is_file():
            detail = _format_isolated_runner_failure(action, returncode=completed.returncode, stderr=completed.stderr)
            if action == "train":
                return _training_error_result(config, detail)
            return _loss_landscape_error_result(detail)

        try:
            response = _ipc_decode(json.loads(output_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
            detail = _format_isolated_runner_failure(action, error=f"{type(exc).__name__}: {exc}")
            if action == "train":
                return _training_error_result(config, detail)
            return _loss_landscape_error_result(detail)

    if not isinstance(response, Mapping) or not response.get("ok"):
        detail = _format_isolated_runner_failure(
            action,
            error=f"{response.get('error_type', 'Error')}: {response.get('error', '')}" if isinstance(response, Mapping) else "",
        )
        if action == "train":
            return _training_error_result(config, detail)
        return _loss_landscape_error_result(detail)

    result = response.get("result")
    if not isinstance(result, dict):
        detail = _format_isolated_runner_failure(action, error="runner returned an invalid payload")
        if action == "train":
            return _training_error_result(config, detail)
        return _loss_landscape_error_result(detail)
    return result


def _session_state_get(key: str, default: Any = None) -> Any:
    state = getattr(st, "session_state", None)
    if state is None:
        return default
    try:
        return state.get(key, default)
    except AttributeError:
        try:
            return state[key]
        except KeyError:
            return default


def _session_state_set(key: str, value: Any) -> None:
    state = getattr(st, "session_state", None)
    if state is not None:
        state[key] = value


def _resolve_trained_config(
    current_config: PlaygroundConfig,
    preset_label: str,
    *,
    train_requested: bool,
    force_refresh: bool = False,
) -> tuple[PlaygroundConfig, str, bool]:
    stored_payload = _session_state_get(TRAINED_CONFIG_STATE_KEY)
    if stored_payload is None or train_requested or force_refresh:
        _session_state_set(TRAINED_CONFIG_STATE_KEY, _config_state_payload(current_config))
        _session_state_set(TRAINED_PRESET_STATE_KEY, preset_label)
        return current_config, preset_label, False

    if not isinstance(stored_payload, Mapping):
        stored_payload = _config_state_payload(current_config)
        _session_state_set(TRAINED_CONFIG_STATE_KEY, stored_payload)
        _session_state_set(TRAINED_PRESET_STATE_KEY, preset_label)

    trained_config = _config_from_payload({"config": stored_payload})
    trained_preset = str(_session_state_get(TRAINED_PRESET_STATE_KEY, preset_label))
    return trained_config, trained_preset, _config_signature(current_config) != _config_signature(trained_config)


@st.cache_data(show_spinner=False)
def _cached_train(payload: dict[str, Any]) -> dict[str, Any]:
    config = _config_from_cache_payload(payload)
    if _use_isolated_torch_training():
        return _run_core_in_subprocess("train", config)
    return _train_playground(config)


@st.cache_data(show_spinner=False)
def _cached_loss_landscape(payload: dict[str, Any], resolution: int, span: float) -> dict[str, Any]:
    config = _config_from_cache_payload(payload)
    if _use_isolated_torch_training():
        return _run_core_in_subprocess("loss_landscape", config, resolution=resolution, span=span)
    return _loss_landscape(config, resolution=resolution, span=span)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_evidence_frame(path: Path, empty: pd.DataFrame) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (OSError, ValueError, pd.errors.EmptyDataError, pd.errors.ParserError):
        return empty.copy()


def _load_evidence_result(evidence_dir: Path) -> tuple[PlaygroundConfig, dict[str, Any], Path] | None:
    root = Path(evidence_dir).expanduser()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        return None

    manifest = _read_json_file(manifest_path)
    config_payload = manifest.get("config")
    if not isinstance(config_payload, Mapping):
        config_payload = _read_json_file(root / "config" / "playground_config.json").get("config", {})
    config = _config_from_payload({"config": config_payload})

    samples = _read_evidence_frame(root / "data" / "samples.csv", pd.DataFrame(columns=["x1", "x2", "target"]))
    history = _read_evidence_frame(
        root / "data" / "training_history.csv",
        pd.DataFrame(columns=["epoch", "train_loss", "validation_loss", "train_accuracy", "validation_accuracy"]),
    )
    grid = _read_evidence_frame(root / "data" / "decision_grid.csv", pd.DataFrame(columns=["x1", "x2", "probability"]))
    boundary_snapshots = _read_evidence_frame(root / "data" / "boundary_snapshots.csv", _empty_boundary_snapshots())
    network_layers = _read_evidence_frame(root / "model" / "network_layers.csv", _empty_network_layers())
    activation_maps = _read_evidence_frame(root / "model" / "hidden_activation_maps.csv", _empty_activation_maps())
    loss_landscape = _read_evidence_frame(root / "model" / "loss_landscape.csv", _empty_loss_landscape())
    summary_payload = _read_json_file(root / "summary" / "run_summary.json")

    summary = manifest.get("summary")
    if not isinstance(summary, Mapping):
        summary = summary_payload.get("summary", {})
    landscape_summary = manifest.get("landscape_summary")
    if not isinstance(landscape_summary, Mapping):
        landscape_summary = summary_payload.get("landscape_summary", _loss_landscape_summary(loss_landscape))

    return (
        config,
        {
            "status": "ok",
            "detail": "",
            "samples": samples,
            "history": history,
            "grid": grid,
            "boundary_snapshots": boundary_snapshots,
            "network_layers": network_layers,
            "activation_maps": activation_maps,
            "loss_landscape": loss_landscape,
            "summary": dict(summary) if isinstance(summary, Mapping) else {},
            "landscape_summary": dict(landscape_summary) if isinstance(landscape_summary, Mapping) else {},
        },
        root,
    )


def _load_latest_evidence_result(
    evidence_dirs: Sequence[str | Path] | None,
) -> tuple[PlaygroundConfig, dict[str, Any], Path] | None:
    candidates: list[tuple[float, Path]] = []
    for raw_path in evidence_dirs or ():
        root = Path(raw_path).expanduser()
        manifest_path = root / "manifest.json"
        try:
            candidates.append((manifest_path.stat().st_mtime, root))
        except OSError:
            continue
    for _mtime, root in sorted(candidates, reverse=True):
        loaded = _load_evidence_result(root)
        if loaded is not None:
            return loaded
    return None


def _render_page_styles() -> None:
    st.markdown(
        """
<style>
.agilab-pt-hero {
  border: 1px solid rgba(247, 242, 232, 0.18);
  border-left: 4px solid var(--agilab-value-ready, #72d6b4);
  border-radius: 8px;
  padding: 1rem 1.1rem;
  margin: 0.25rem 0 1rem;
  background: linear-gradient(135deg, rgba(8, 17, 31, 0.94), rgba(18, 43, 51, 0.86) 56%, rgba(38, 48, 25, 0.78));
  box-shadow: 0 16px 44px rgba(7, 17, 31, 0.16), inset 0 1px 0 rgba(255,255,255,0.08);
}
.agilab-pt-kicker {
  color: var(--agilab-value-ready, #72d6b4);
  font-size: 0.78rem;
  font-weight: 800;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}
.agilab-pt-hero h1 {
  color: #f8fafc;
  font-size: 2.35rem;
  line-height: 1.05;
  margin: 0.2rem 0 0.55rem;
}
.agilab-pt-hero p {
  color: #cbd5e1;
  font-size: 1.02rem;
  max-width: 62rem;
  margin: 0;
}
.agilab-pt-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 0.55rem;
  margin-top: 1rem;
}
.agilab-pt-chip {
  border: 1px solid rgba(226, 232, 240, 0.22);
  border-radius: 8px;
  color: #e2e8f0;
  background: rgba(15, 23, 42, 0.55);
  padding: 0.34rem 0.58rem;
  font-size: 0.82rem;
}
.agilab-pt-summary-banner {
  border: 1px solid rgba(247, 242, 232, 0.18);
  border-radius: 8px;
  padding: 0.95rem 1.05rem;
  margin: 0.2rem 0 0.85rem;
  background: linear-gradient(135deg, rgba(8, 17, 31, 0.94), rgba(18, 43, 51, 0.86));
  box-shadow: 0 12px 32px rgba(7, 17, 31, 0.14), inset 0 1px 0 rgba(255,255,255,0.07);
}
.agilab-pt-summary-kicker {
  color: rgba(247, 242, 232, 0.68);
  font-size: 0.7rem;
  font-weight: 820;
  letter-spacing: 0.085em;
  line-height: 1.15;
  text-transform: uppercase;
}
.agilab-pt-summary-headline {
  color: #f7f2e8;
  font-size: 1.35rem;
  font-weight: 860;
  line-height: 1.15;
  margin-top: 0.3rem;
}
.agilab-pt-summary-context {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin-top: 0.75rem;
}
.agilab-pt-compact-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem;
  margin: 0.15rem 0 0.65rem;
}
.agilab-pt-run-panel {
  display: grid;
  grid-template-columns: minmax(13rem, 1fr) minmax(24rem, 2fr);
  gap: 0.85rem 1rem;
  align-items: stretch;
  border: 1px solid rgba(247, 242, 232, 0.18);
  border-radius: 8px;
  padding: 0.85rem 0.95rem;
  margin: 0.15rem 0 0.7rem;
  background: linear-gradient(135deg, rgba(8, 17, 31, 0.94), rgba(18, 43, 51, 0.86));
  box-shadow: 0 12px 32px rgba(7, 17, 31, 0.14), inset 0 1px 0 rgba(255,255,255,0.07);
}
.agilab-pt-run-main {
  min-width: 0;
}
.agilab-pt-run-kicker {
  color: rgba(247, 242, 232, 0.68);
  font-size: 0.68rem;
  font-weight: 820;
  letter-spacing: 0.085em;
  line-height: 1.15;
  text-transform: uppercase;
}
.agilab-pt-run-headline {
  color: #f7f2e8;
  font-size: 1.32rem;
  font-weight: 860;
  line-height: 1.12;
  margin-top: 0.28rem;
}
.agilab-pt-run-note {
  color: rgba(247, 242, 232, 0.62);
  font-size: 0.85rem;
  line-height: 1.3;
  margin-top: 0.35rem;
}
.agilab-pt-run-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.55rem;
}
.agilab-pt-run-metric {
  min-width: 0;
  border: 1px solid rgba(247, 242, 232, 0.14);
  border-radius: 8px;
  padding: 0.6rem 0.68rem;
  background: rgba(247, 242, 232, 0.035);
}
.agilab-pt-run-metric-label {
  color: rgba(247, 242, 232, 0.62);
  font-size: 0.68rem;
  font-weight: 820;
  letter-spacing: 0.075em;
  line-height: 1.15;
  text-transform: uppercase;
}
.agilab-pt-run-metric-value {
  color: #f7f2e8;
  font-size: 1.12rem;
  font-weight: 860;
  line-height: 1.05;
  margin-top: 0.24rem;
}
.agilab-pt-run-metric-note {
  color: rgba(247, 242, 232, 0.58);
  font-size: 0.74rem;
  line-height: 1.25;
  margin-top: 0.22rem;
}
.agilab-pt-run-context {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 0.42rem;
  margin-top: -0.05rem;
}
.agilab-header-card {
  position: relative;
  display: grid;
  grid-template-rows: auto minmax(1.65rem, 1fr) auto;
  align-content: stretch;
  box-sizing: border-box;
  width: 100%;
  height: 100%;
  min-height: 6.25rem;
  padding: 0.78rem 0.86rem 0.72rem 0.95rem;
  border: 1px solid rgba(247, 242, 232, 0.16);
  border-radius: 8px;
  background: linear-gradient(145deg, rgba(255,255,255,0.075), rgba(255,255,255,0.025)), rgba(247, 242, 232, 0.03);
  box-shadow: inset 0 1px 0 rgba(255,255,255,0.075), 0 10px 28px rgba(0,0,0,0.12);
  overflow: hidden;
}
.agilab-header-card::before {
  content: "";
  position: absolute;
  inset: 0.62rem auto 0.62rem 0.52rem;
  width: 3px;
  border-radius: 999px;
  background: rgba(247, 242, 232, 0.78);
  opacity: 0.82;
}
.agilab-header-card--ready::before {
  background: #72d6b4;
}
.agilab-header-card--incomplete::before {
  background: #ffbe5e;
}
.agilab-header-label {
  position: relative;
  z-index: 1;
  color: rgba(247, 242, 232, 0.68);
  font-size: 0.7rem;
  font-weight: 820;
  letter-spacing: 0.085em;
  line-height: 1.15;
  text-transform: uppercase;
}
.agilab-header-value {
  position: relative;
  z-index: 1;
  align-self: center;
  margin-top: 0.22rem;
  color: #f7f2e8;
  font-size: 1.28rem;
  font-weight: 860;
  line-height: 1.1;
  overflow-wrap: anywhere;
}
.agilab-header-value--ready {
  color: #72d6b4 !important;
}
.agilab-header-value--incomplete {
  color: #ffbe5e !important;
}
.agilab-header-caption {
  position: relative;
  z-index: 1;
  align-self: end;
  margin-top: 0.45rem;
  color: rgba(247, 242, 232, 0.60);
  font-size: 0.75rem;
  line-height: 1.3;
  overflow-wrap: anywhere;
}
.agilab-pt-card {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  padding: 1rem;
  min-height: 9.25rem;
  background: rgba(11, 18, 32, 0.84);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.05);
}
.agilab-pt-card strong {
  display: block;
  color: #e2e8f0;
  font-size: 0.82rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}
.agilab-pt-value {
  color: #f8fafc;
  font-size: 2rem;
  font-weight: 800;
  margin: 0.2rem 0 0.25rem;
}
.agilab-pt-note {
  color: #94a3b8;
  font-size: 0.86rem;
}
.agilab-pt-section {
  border-left: 4px solid #38bdf8;
  padding: 0.25rem 0 0.25rem 0.9rem;
  margin-bottom: 0.8rem;
}
.agilab-pt-section strong {
  color: #e2e8f0;
}
.agilab-pt-section span {
  color: #94a3b8;
}
.agilab-pt-guide {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.75rem;
  margin: 0.6rem 0 1rem;
}
.agilab-pt-step {
  border: 1px solid rgba(148, 163, 184, 0.20);
  border-radius: 8px;
  padding: 0.85rem 0.9rem;
  background: rgba(15, 23, 42, 0.58);
}
.agilab-pt-step-active {
  border-color: rgba(251, 191, 36, 0.64);
  background: rgba(88, 55, 16, 0.38);
}
.agilab-pt-step-ready {
  border-color: rgba(34, 197, 94, 0.46);
}
.agilab-pt-step strong {
  color: #f8fafc;
  display: block;
}
.agilab-pt-step span {
  color: #94a3b8;
  font-size: 0.86rem;
}
.agilab-pt-insight {
  border: 1px solid rgba(125, 211, 252, 0.18);
  border-radius: 8px;
  padding: 0.9rem;
  background: rgba(8, 13, 26, 0.66);
  min-height: 7rem;
}
.agilab-pt-insight strong {
  color: #e0f2fe;
  display: block;
  margin-bottom: 0.25rem;
}
.agilab-pt-insight span {
  color: #94a3b8;
  font-size: 0.88rem;
}
.agilab-pt-coach {
  border: 1px solid rgba(251, 191, 36, 0.22);
  border-radius: 8px;
  padding: 0.95rem;
  margin: 0.35rem 0 1rem;
  background:
    radial-gradient(circle at top left, rgba(251, 191, 36, 0.15), transparent 30rem),
    rgba(8, 13, 26, 0.78);
}
.agilab-pt-coach-head {
  color: #f8fafc;
  font-size: 1.02rem;
  font-weight: 850;
  margin-bottom: 0.2rem;
}
.agilab-pt-coach-note {
  color: #94a3b8;
  font-size: 0.87rem;
  margin-bottom: 0.75rem;
}
.agilab-pt-coach-card {
  border: 1px solid rgba(148, 163, 184, 0.22);
  border-radius: 8px;
  min-height: 10.4rem;
  padding: 0.85rem 0.9rem;
  background: rgba(15, 23, 42, 0.68);
}
.agilab-pt-coach-card strong {
  color: #f8fafc;
  display: block;
  font-size: 0.96rem;
  margin-bottom: 0.35rem;
}
.agilab-pt-coach-card span {
  color: #94a3b8;
  display: block;
  font-size: 0.84rem;
  line-height: 1.35;
  margin-bottom: 0.5rem;
}
.agilab-pt-coach-card code {
  color: #fde68a;
}
.agilab-pt-coach-card a {
  color: #7dd3fc;
  font-weight: 760;
  text-decoration: none;
}
.agilab-pt-network-map {
  border: 1px solid rgba(125, 211, 252, 0.18);
  border-radius: 8px;
  padding: 0.85rem;
  margin: 0.2rem 0 0.8rem;
  background: rgba(8, 13, 26, 0.70);
  overflow-x: auto;
}
.agilab-pt-network-row {
  align-items: center;
  display: flex;
  gap: 0.55rem;
  min-width: max-content;
}
.agilab-pt-network-layer {
  border: 1px solid rgba(148, 163, 184, 0.24);
  border-radius: 8px;
  min-width: 7.4rem;
  padding: 0.65rem 0.75rem;
  background: rgba(15, 23, 42, 0.72);
}
.agilab-pt-network-layer strong {
  color: #f8fafc;
  display: block;
  font-size: 0.86rem;
}
.agilab-pt-network-layer span {
  color: #94a3b8;
  display: block;
  font-size: 0.78rem;
  margin-top: 0.16rem;
}
.agilab-pt-network-edge {
  color: #7dd3fc;
  font-size: 1.4rem;
  font-weight: 860;
}
@media (max-width: 860px) {
  .agilab-pt-guide {
    grid-template-columns: 1fr;
  }
  .agilab-pt-run-panel,
  .agilab-pt-run-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
""",
        unsafe_allow_html=True,
    )


def _finite_number(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(number):
        return default
    return number


def _format_percent(value: Any) -> str:
    number = _finite_number(value)
    return f"{max(0.0, min(1.0, number)) * 100:.0f}%"


def _format_percentage_points(value: Any) -> str:
    return f"{abs(_finite_number(value)) * 100:.1f} pp"


def _confidence_score(grid: pd.DataFrame) -> float:
    if grid.empty or "probability" not in grid:
        return 0.0
    probabilities = grid["probability"].to_numpy(dtype=float)
    if probabilities.size == 0:
        return 0.0
    return float(np.mean(np.abs(probabilities - 0.5) * 2.0))


def _class_balance(samples: pd.DataFrame) -> str:
    if samples.empty or "target" not in samples:
        return "no samples"
    counts = samples["target"].value_counts(normalize=True)
    if counts.empty:
        return "no samples"
    majority = float(counts.max())
    minority = float(counts.min())
    return f"{minority * 100:.0f}/{majority * 100:.0f}% class split"


def _parameter_count(layers: pd.DataFrame) -> int:
    if layers.empty or "parameters" not in layers:
        return 0
    return int(pd.to_numeric(layers["parameters"], errors="coerce").fillna(0).sum())


def _generalization_gap(summary: Mapping[str, Any]) -> float:
    train_accuracy = _finite_number(summary.get("train_accuracy", 0.0))
    validation_accuracy = _finite_number(summary.get("validation_accuracy", 0.0))
    gap = train_accuracy - validation_accuracy
    return gap if np.isfinite(gap) else 0.0


def _run_quality_label(validation_accuracy: float, gap: float) -> str:
    if validation_accuracy >= 0.9 and gap <= 0.05:
        return "Strong run"
    if validation_accuracy >= 0.8 and gap <= 0.12:
        return "Usable run"
    if validation_accuracy >= 0.7:
        return "Learning run"
    return "Needs tuning"


def _gap_quality_label(gap: float) -> str:
    if gap <= 0:
        return "validation matches train"
    if gap <= 0.05:
        return "low overfit"
    if gap <= 0.12:
        return "moderate overfit"
    return "high overfit"


def _gap_state(gap: float) -> str:
    return "ready" if gap <= 0.12 else "incomplete"


def _decision_confidence_note(confidence: float) -> str:
    if confidence >= 0.65:
        return "clear boundary"
    if confidence >= 0.35:
        return "boundary forming"
    return "soft boundary"


def _summary_sample_count(summary: Mapping[str, Any], samples: pd.DataFrame) -> int:
    try:
        count = int(summary.get("samples", len(samples)) or len(samples))
    except (TypeError, ValueError, OverflowError):
        count = len(samples)
    return count if count >= 0 else len(samples)


def _metric_card(label: str, value: str, note: str, *, state: str = "ready") -> str:
    css_state = html.escape(state)
    return (
        f'<div class="agilab-header-card agilab-header-card--{css_state}">'
        f'<div class="agilab-header-label">{html.escape(label)}</div>'
        f'<div class="agilab-header-value agilab-header-value--{css_state}">{html.escape(value)}</div>'
        f'<div class="agilab-header-caption">{html.escape(note)}</div>'
        "</div>"
    )


def _summary_banner(headline: str, chips: Sequence[str]) -> str:
    chip_html = "".join(f'<span class="agilab-pt-chip">{html.escape(chip)}</span>' for chip in chips)
    return (
        '<div class="agilab-pt-summary-banner">'
        '<div class="agilab-pt-summary-kicker">Run quality</div>'
        f'<div class="agilab-pt-summary-headline">{html.escape(headline)}</div>'
        f'<div class="agilab-pt-summary-context">{chip_html}</div>'
        "</div>"
    )


def _summary_chips(
    *,
    config: PlaygroundConfig,
    samples: pd.DataFrame,
    parameter_count: int,
    sample_count: int,
) -> list[str]:
    return [
        f"{parameter_count:,} params",
        f"{len(config.hidden_layers)} hidden layer(s)",
        f"{sample_count:,} samples",
        _class_balance(samples),
    ]


def _compact_metric(label: str, value: str, note: str) -> str:
    return (
        '<div class="agilab-pt-run-metric">'
        f'<div class="agilab-pt-run-metric-label">{html.escape(label)}</div>'
        f'<div class="agilab-pt-run-metric-value">{html.escape(value)}</div>'
        f'<div class="agilab-pt-run-metric-note">{html.escape(note)}</div>'
        "</div>"
    )


def _compact_summary_panel(
    *,
    run_quality: str,
    gap_note: str,
    confidence_note: str,
    validation_value: str,
    gap_value: str,
    confidence_value: str,
    chips: Sequence[str],
) -> str:
    chip_html = "".join(f'<span class="agilab-pt-chip">{html.escape(chip)}</span>' for chip in chips)
    return (
        '<div class="agilab-pt-run-panel">'
        '<div class="agilab-pt-run-main">'
        '<div class="agilab-pt-run-kicker">Run quality</div>'
        f'<div class="agilab-pt-run-headline">{html.escape(run_quality)}</div>'
        f'<div class="agilab-pt-run-note">{html.escape(gap_note)}</div>'
        "</div>"
        '<div class="agilab-pt-run-metrics">'
        + _compact_metric("Validation", validation_value, "held-out accuracy")
        + _compact_metric("Train-val gap", gap_value, gap_note)
        + _compact_metric("Decision confidence", confidence_value, confidence_note)
        + "</div>"
        f'<div class="agilab-pt-run-context">{chip_html}</div>'
        "</div>"
    )


def _guide_step(title: str, text: str, css_class: str) -> str:
    return (
        f'<div class="agilab-pt-step {html.escape(css_class)}">'
        f"<strong>{html.escape(title)}</strong>"
        f"<span>{html.escape(text)}</span>"
        "</div>"
    )


def _render_guided_flow(*, pending_changes: bool, result_status: str) -> None:
    first_class = "agilab-pt-step-active" if pending_changes else "agilab-pt-step-ready"
    first_text = "Controls changed. Press Train / refresh to update charts." if pending_changes else "Run evidence matches the current charts."
    second_class = "agilab-pt-step-ready" if result_status == "ok" else ""
    third_class = "agilab-pt-step-ready" if result_status == "ok" and not pending_changes else ""
    st.markdown(
        '<div class="agilab-pt-guide">'
        + _guide_step("1. Train", first_text, first_class)
        + _guide_step("2. Inspect", "Read the boundary, curves, neurons, and terrain.", second_class)
        + _guide_step("3. Reuse", "Download evidence or share the replay token.", third_class)
        + "</div>",
        unsafe_allow_html=True,
    )


def _performance_band(summary: Mapping[str, Any]) -> tuple[str, str]:
    validation_accuracy = float(summary.get("validation_accuracy", 0.0) or 0.0)
    if validation_accuracy >= 0.9:
        return "Strong fit", "Validation accuracy is high enough for a clean visual demo."
    if validation_accuracy >= 0.75:
        return "Learning visible", "The model has learned structure; tune capacity or features to sharpen it."
    return "Still searching", "Try a stronger preset, more epochs, or more informative features."


def _gap_band(summary: Mapping[str, Any]) -> tuple[str, str]:
    gap = _generalization_gap(summary)
    if gap <= 0.05:
        return "Generalizes well", "Train and validation accuracy stay close."
    if gap <= 0.15:
        return "Watch the gap", "There is mild overfit; reduce capacity or increase data/noise realism."
    return "Likely overfit", "Training is ahead of validation; prefer simpler layers or more data."


def _confidence_band(grid: pd.DataFrame) -> tuple[str, str]:
    confidence = _confidence_score(grid)
    if confidence >= 0.65:
        return "Decisive boundary", "Most grid cells are far from the 0.5 indecision frontier."
    if confidence >= 0.35:
        return "Boundary forming", "The surface is readable but still uncertain around several regions."
    return "Soft boundary", "The network is unsure; inspect features, epochs, and hidden-layer capacity."


def _render_interpretation_cards(result: Mapping[str, Any]) -> None:
    summary = result.get("summary", {})
    grid = _result_frame(result, "grid", pd.DataFrame(columns=["x1", "x2", "probability"]))
    cards = [
        _performance_band(summary),
        _gap_band(summary),
        _confidence_band(grid),
    ]
    columns = st.columns(3)
    for column, (title, text) in zip(columns, cards, strict=False):
        with column:
            st.markdown(
                '<div class="agilab-pt-insight">'
                f"<strong>{html.escape(title)}</strong>"
                f"<span>{html.escape(text)}</span>"
                "</div>",
                unsafe_allow_html=True,
            )


def _bounded_layer_width(value: float) -> int:
    return max(1, min(256, int(round(value))))


def _simpler_hidden_layers(hidden_layers: Sequence[int]) -> tuple[int, ...]:
    if not hidden_layers:
        return (4,)
    reduced = tuple(_bounded_layer_width(width * 0.65) for width in hidden_layers)
    if len(reduced) > 1:
        reduced = reduced[:-1]
    return reduced or (4,)


def _wider_hidden_layers(hidden_layers: Sequence[int]) -> tuple[int, ...]:
    if not hidden_layers:
        return (8, 8)
    widened = tuple(_bounded_layer_width(width * 1.35) for width in hidden_layers)
    if len(widened) < 3:
        widened = (*widened, max(4, widened[-1]))
    return widened[:4]


def _feature_boost(config: PlaygroundConfig) -> tuple[str, ...]:
    preferred_by_dataset = {
        "xor": ("x1", "x2", "x1_x2", "x1_squared", "x2_squared"),
        "spiral": ("x1", "x2", "sin_x1", "sin_x2", "x1_x2"),
        "circles": DEFAULT_FEATURES,
        "gaussian": ("x1", "x2", "x1_x2"),
    }
    preferred = preferred_by_dataset.get(config.dataset, DEFAULT_FEATURES)
    features = list(config.feature_names)
    for feature in preferred:
        if feature in FEATURES and feature not in features:
            features.append(feature)
    return tuple(features[: len(FEATURES)])


def _coach_url(config: PlaygroundConfig) -> str:
    return f"?pytorch_playground={_encode_share_config(config)}"


def _tuning_recommendations(config: PlaygroundConfig, result: Mapping[str, Any]) -> list[dict[str, str]]:
    """Return replayable next experiments based on the visible run state."""
    summary = result.get("summary", {})
    if not isinstance(summary, Mapping):
        summary = {}
    grid = _result_frame(result, "grid", pd.DataFrame(columns=["x1", "x2", "probability"]))
    validation_accuracy = _finite_number(summary.get("validation_accuracy", 0.0))
    gap = _generalization_gap(summary)
    confidence = _confidence_score(grid)
    recommendations: list[dict[str, str]] = []
    seen_signatures = {_config_signature(config)}

    def _add(title: str, why: str, change: str, candidate: PlaygroundConfig) -> None:
        signature = _config_signature(candidate)
        if signature in seen_signatures:
            return
        seen_signatures.add(signature)
        recommendations.append(
            {
                "title": title,
                "why": why,
                "change": change,
                "url": _coach_url(candidate),
                "token": _encode_share_config(candidate),
            }
        )

    if gap > 0.12:
        candidate = replace(
            config,
            hidden_layers=_simpler_hidden_layers(config.hidden_layers),
            sample_count=min(1000, max(config.sample_count + 96, int(config.sample_count * 1.2))),
            epochs=max(40, int(config.epochs * 0.85)),
            learning_rate=max(0.001, config.learning_rate * 0.85),
        )
        _add(
            "Reduce overfit",
            f"Train is ahead of validation by {_format_percentage_points(gap)}.",
            "Simpler network, slightly more data, lower learning rate.",
            candidate,
        )

    if validation_accuracy < 0.82 or confidence < 0.35:
        candidate = replace(
            config,
            hidden_layers=_wider_hidden_layers(config.hidden_layers),
            epochs=min(300, max(config.epochs + 40, int(config.epochs * 1.35))),
            learning_rate=min(0.2, config.learning_rate * 1.15),
            grid_size=min(120, max(config.grid_size + 8, int(config.grid_size * 1.1))),
        )
        _add(
            "Sharpen the boundary",
            f"Validation is {_format_percent(validation_accuracy)} and confidence is {_format_percent(confidence)}.",
            "More capacity, more epochs, finer surface.",
            candidate,
        )

    boosted_features = _feature_boost(config)
    if boosted_features != config.feature_names:
        candidate = replace(
            config,
            feature_names=boosted_features,
            epochs=min(300, max(config.epochs + 20, config.epochs)),
        )
        _add(
            "Try richer features",
            "The current feature set leaves useful nonlinear signals unused.",
            "Add engineered features while keeping the same challenge.",
            candidate,
        )

    candidate = replace(
        config,
        sample_count=max(96, min(config.sample_count, 256)),
        epochs=max(30, min(config.epochs, 70)),
        grid_size=max(40, min(config.grid_size, 64)),
    )
    _add(
        "Make a fast replay",
        "Use this when the goal is a quick live demo rather than maximum accuracy.",
        "Smaller run, same dataset, same model shape.",
        candidate,
    )

    candidate = replace(
        config,
        grid_size=min(120, max(config.grid_size, 104)),
        epochs=min(300, max(config.epochs, 120)),
    )
    _add(
        "Export a cleaner visual",
        "Use this when the boundary already works and the artifact should look publication-ready.",
        "Finer grid and longer training for smoother evidence.",
        candidate,
    )

    return recommendations[:3]


def _render_experiment_coach(config: PlaygroundConfig, result: Mapping[str, Any]) -> None:
    recommendations = _tuning_recommendations(config, result)
    if not recommendations:
        return
    st.markdown(
        """
<div class="agilab-pt-coach">
  <div class="agilab-pt-coach-head">Experiment coach</div>
  <div class="agilab-pt-coach-note">
    Classic neural playgrounds expose knobs. AGILAB adds replayable next
    experiments: each card is a share token you can open, train, and export as evidence.
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    columns = st.columns(len(recommendations))
    for column, recommendation in zip(columns, recommendations, strict=False):
        with column:
            st.markdown(
                '<div class="agilab-pt-coach-card">'
                f"<strong>{html.escape(recommendation['title'])}</strong>"
                f"<span>{html.escape(recommendation['why'])}</span>"
                f"<span><code>{html.escape(recommendation['change'])}</code></span>"
                f'<a href="{html.escape(recommendation["url"])}" target="_self">Open replay config</a>'
                "</div>",
                unsafe_allow_html=True,
            )


def _network_layer_cards(config: PlaygroundConfig, layers: pd.DataFrame) -> list[dict[str, str]]:
    cards = [
        {
            "title": "Inputs",
            "value": f"{len(config.feature_names)} feature(s)",
            "detail": ", ".join(config.feature_names),
        }
    ]
    for index, width in enumerate(config.hidden_layers, start=1):
        parameters = ""
        if not layers.empty and "layer" in layers and "parameters" in layers:
            candidates = layers[layers["layer"] == index]
            if not candidates.empty:
                parameters = f"{int(candidates.iloc[0]['parameters']):,} params"
        cards.append(
            {
                "title": f"Hidden {index}",
                "value": f"{int(width)} neurons",
                "detail": parameters or config.activation,
            }
        )
    cards.append(
        {
            "title": "Output",
            "value": "2 classes",
            "detail": "softmax boundary",
        }
    )
    return cards


def _network_architecture_html(config: PlaygroundConfig, layers: pd.DataFrame) -> str:
    parts: list[str] = ['<div class="agilab-pt-network-map"><div class="agilab-pt-network-row">']
    for index, card in enumerate(_network_layer_cards(config, layers)):
        if index:
            parts.append('<div class="agilab-pt-network-edge">→</div>')
        parts.append(
            '<div class="agilab-pt-network-layer">'
            f"<strong>{html.escape(card['title'])}</strong>"
            f"<span>{html.escape(card['value'])}</span>"
            f"<span>{html.escape(card['detail'])}</span>"
            "</div>"
        )
    parts.append("</div></div>")
    return "".join(parts)


def _boundary_snapshot_grid(result: Mapping[str, Any], final_grid: pd.DataFrame) -> pd.DataFrame:
    snapshots = _result_frame(result, "boundary_snapshots", _empty_boundary_snapshots())
    if snapshots.empty or "epoch" not in snapshots:
        return final_grid
    epochs = sorted(int(value) for value in pd.to_numeric(snapshots["epoch"], errors="coerce").dropna().unique())
    if not epochs:
        return final_grid
    selectbox = getattr(st, "selectbox", None)
    selected_epoch = (
        selectbox(
            "Boundary epoch",
            epochs,
            index=len(epochs) - 1,
            help="Step through stored learning snapshots before the final evidence export.",
        )
        if callable(selectbox)
        else epochs[-1]
    )
    selected = snapshots[snapshots["epoch"].astype(int) == int(selected_epoch)].drop(columns=["epoch"], errors="ignore")
    return selected if not selected.empty else final_grid


def _render_hero(active_app: Path | None, preset_label: str, config: PlaygroundConfig) -> None:
    chips = [
        f"dataset: {config.dataset}",
        f"features: {len(config.feature_names)}",
        f"network: {'-'.join(str(width) for width in config.hidden_layers) or 'linear'}",
        f"regularization: {config.regularization}",
        f"epochs: {config.epochs}",
    ]
    if active_app is not None:
        chips.insert(0, f"app: {active_app.name}")
    chip_html = "".join(f'<span class="agilab-pt-chip">{html.escape(chip)}</span>' for chip in chips)
    st.markdown(
        f"""
<div class="agilab-pt-hero">
  <div class="agilab-pt-kicker">Neural boundary lab</div>
  <h1>{html.escape(PAGE_TITLE)}</h1>
  <p>
    Pick a visual challenge, train a real PyTorch classifier, then inspect the
    decision surface, neuron activations, loss terrain, and reproducible evidence pack.
  </p>
  <div class="agilab-pt-strip">
    <span class="agilab-pt-chip">{html.escape(preset_label)}</span>
    {chip_html}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _render_compact_header(active_app: Path | None, preset_label: str, config: PlaygroundConfig) -> None:
    app_label = active_app.name if active_app is not None else "standalone"
    network = "-".join(str(width) for width in config.hidden_layers) or "linear"
    chips = [
        preset_label,
        f"app: {app_label}",
        f"dataset: {config.dataset}",
        f"features: {len(config.feature_names)}",
        f"network: {network}",
        f"regularization: {config.regularization}",
        f"epochs: {config.epochs}",
    ]
    st.markdown(
        '<div class="agilab-pt-compact-meta">'
        + "".join(f'<span class="agilab-pt-chip">{html.escape(chip)}</span>' for chip in chips)
        + "</div>",
        unsafe_allow_html=True,
    )


def _render_section_intro(title: str, text: str) -> None:
    st.markdown(
        f"""
<div class="agilab-pt-section">
  <strong>{html.escape(title)}</strong><br>
  <span>{html.escape(text)}</span>
</div>
""",
        unsafe_allow_html=True,
    )


def _grid_axes(grid: pd.DataFrame, fallback_grid_size: int) -> tuple[np.ndarray, np.ndarray]:
    if grid.empty:
        return np.array([], dtype=float), np.array([], dtype=float)
    x_axis = np.array(sorted(grid["x1"].unique()), dtype=float)
    y_axis = np.array(sorted(grid["x2"].unique()), dtype=float)
    if len(x_axis) * len(y_axis) == len(grid):
        return x_axis, y_axis
    size = int(round(np.sqrt(len(grid)))) or max(1, int(fallback_grid_size))
    axis = np.linspace(-1.35, 1.35, size)
    return axis, axis


def _decision_figure(samples: pd.DataFrame, grid: pd.DataFrame, grid_size: int) -> go.Figure:
    if go is None:
        trace_count = len(tuple(samples.groupby("target", sort=True))) + (2 if not grid.empty else 0)
        return _plotly_unavailable_figure("Decision boundary", trace_count)  # type: ignore[return-value]
    figure = go.Figure()
    if not grid.empty:
        x_axis, y_axis = _grid_axes(grid, grid_size)
        z = (
            grid.pivot_table(index="x2", columns="x1", values="probability", aggfunc="mean")
            .reindex(index=y_axis, columns=x_axis)
            .to_numpy()
        )
        figure.add_trace(
            go.Contour(
                x=x_axis,
                y=y_axis,
                z=z,
                colorscale=[[0.0, "#0ea5e9"], [0.48, "#111827"], [0.52, "#f8fafc"], [1.0, "#fb7185"]],
                contours={"start": 0.0, "end": 1.0, "size": 0.05, "coloring": "heatmap"},
                opacity=0.82,
                showscale=False,
                hoverinfo="skip",
                name="class probability",
            )
        )
        figure.add_trace(
            go.Contour(
                x=x_axis,
                y=y_axis,
                z=z,
                contours={"start": 0.5, "end": 0.5, "size": 0.5, "coloring": "lines"},
                line={"width": 3, "color": "#f8fafc"},
                showscale=False,
                hoverinfo="skip",
                name="decision boundary",
            )
        )

    colors = {0: "#38bdf8", 1: "#fb7185"}
    for class_id, group in samples.groupby("target", sort=True):
        figure.add_trace(
            go.Scatter(
                x=group["x1"],
                y=group["x2"],
                mode="markers",
                name=f"class {class_id}",
                marker={
                    "size": 9,
                    "color": colors.get(int(class_id), "#cbd5e1"),
                    "opacity": 0.92,
                    "line": {"width": 1.1, "color": "rgba(255,255,255,0.78)"},
                },
            )
        )
    figure.update_layout(
        height=560,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(7, 13, 28, 0.92)",
        font={"color": "#dbeafe"},
        xaxis={
            "range": [-1.35, 1.35],
            "scaleanchor": "y",
            "zeroline": False,
            "gridcolor": "rgba(148, 163, 184, 0.12)",
        },
        yaxis={"range": [-1.35, 1.35], "zeroline": False, "gridcolor": "rgba(148, 163, 184, 0.12)"},
        legend={"orientation": "h", "y": 1.02, "font": {"color": "#dbeafe"}},
    )
    return figure


def _history_figure(history: pd.DataFrame) -> go.Figure:
    if go is None:
        return _plotly_unavailable_figure("Training history", 4 if not history.empty else 0)  # type: ignore[return-value]
    figure = go.Figure()
    if not history.empty:
        figure.add_trace(
            go.Scatter(
                x=history["epoch"],
                y=history["train_loss"],
                mode="lines",
                name="train loss",
                yaxis="y",
                line={"color": "#38bdf8", "width": 3},
            )
        )
        figure.add_trace(
            go.Scatter(
                x=history["epoch"],
                y=history["validation_loss"],
                mode="lines",
                name="validation loss",
                yaxis="y",
                line={"color": "#fb7185", "width": 3},
            )
        )
        figure.add_trace(
            go.Scatter(
                x=history["epoch"],
                y=history["train_accuracy"],
                mode="lines",
                name="train accuracy",
                yaxis="y2",
                line={"color": "#a7f3d0", "width": 2, "dash": "dot"},
            )
        )
        figure.add_trace(
            go.Scatter(
                x=history["epoch"],
                y=history["validation_accuracy"],
                mode="lines",
                name="validation accuracy",
                yaxis="y2",
                line={"color": "#fde68a", "width": 2, "dash": "dot"},
            )
        )
    figure.update_layout(
        height=280,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(7, 13, 28, 0.86)",
        font={"color": "#dbeafe"},
        yaxis={"title": "loss", "gridcolor": "rgba(148, 163, 184, 0.14)"},
        yaxis2={"title": "accuracy", "overlaying": "y", "side": "right", "range": [0, 1.05], "showgrid": False},
        xaxis={"gridcolor": "rgba(148, 163, 184, 0.10)"},
        legend={"orientation": "h", "y": 1.12},
    )
    return figure


def _activation_figure(activation_maps: pd.DataFrame, layer: int, neuron: int) -> go.Figure:
    if go is None:
        selected = activation_maps[(activation_maps["layer"] == layer) & (activation_maps["neuron"] == neuron)]
        return _plotly_unavailable_figure("Activation map", 1 if not selected.empty else 0)  # type: ignore[return-value]
    figure = go.Figure()
    selected = activation_maps[(activation_maps["layer"] == layer) & (activation_maps["neuron"] == neuron)]
    if not selected.empty:
        x_axis, y_axis = _grid_axes(selected.rename(columns={"activation": "probability"}), 12)
        z = (
            selected.pivot_table(index="x2", columns="x1", values="activation", aggfunc="mean")
            .reindex(index=y_axis, columns=x_axis)
            .to_numpy()
        )
        figure.add_trace(
            go.Contour(
                x=x_axis,
                y=y_axis,
                z=z,
                colorscale=[[0.0, "#020617"], [0.35, "#0ea5e9"], [0.7, "#facc15"], [1.0, "#fb7185"]],
                contours={"coloring": "heatmap"},
                colorbar={"title": "activation"},
            )
        )
    figure.update_layout(
        height=420,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(7, 13, 28, 0.90)",
        font={"color": "#dbeafe"},
        xaxis={
            "range": [-1.35, 1.35],
            "scaleanchor": "y",
            "zeroline": False,
            "gridcolor": "rgba(148, 163, 184, 0.12)",
        },
        yaxis={"range": [-1.35, 1.35], "zeroline": False, "gridcolor": "rgba(148, 163, 184, 0.12)"},
    )
    return figure


def _network_figure(layers: pd.DataFrame) -> go.Figure:
    if go is None:
        return _plotly_unavailable_figure("Network diagnostics", 2 if not layers.empty else 0)  # type: ignore[return-value]
    figure = go.Figure()
    if not layers.empty:
        labels = [f"{row.kind} {int(row.layer)}" for row in layers.itertuples()]
        figure.add_trace(go.Bar(x=labels, y=layers["weight_max_abs"], name="max |weight|", marker_color="#38bdf8"))
        figure.add_trace(go.Bar(x=labels, y=layers["bias_max_abs"], name="max |bias|", marker_color="#fbbf24"))
    figure.update_layout(
        height=260,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(7, 13, 28, 0.84)",
        font={"color": "#dbeafe"},
        yaxis={"title": "magnitude", "gridcolor": "rgba(148, 163, 184, 0.13)"},
        xaxis={"gridcolor": "rgba(148, 163, 184, 0.08)"},
        barmode="group",
        legend={"orientation": "h", "y": 1.08},
    )
    return figure


def _loss_landscape_figure(landscape: pd.DataFrame) -> go.Figure:
    if go is None:
        return _plotly_unavailable_figure("Loss landscape", 3 if not landscape.empty else 0)  # type: ignore[return-value]
    figure = go.Figure()
    if not landscape.empty:
        alpha_axis = np.array(sorted(landscape["alpha"].unique()), dtype=float)
        beta_axis = np.array(sorted(landscape["beta"].unique()), dtype=float)
        z = (
            landscape.pivot_table(index="beta", columns="alpha", values="validation_loss", aggfunc="mean")
            .reindex(index=beta_axis, columns=alpha_axis)
            .to_numpy()
        )
        figure.add_trace(
            go.Surface(
                x=alpha_axis,
                y=beta_axis,
                z=z,
                colorscale=[[0.0, "#22c55e"], [0.45, "#facc15"], [1.0, "#ef4444"]],
                colorbar={"title": "val. loss"},
                opacity=0.94,
            )
        )
        best = landscape.loc[landscape["validation_loss"].idxmin()]
        center_candidates = landscape[landscape["is_center"]]
        center = center_candidates.iloc[0] if not center_candidates.empty else landscape.iloc[len(landscape) // 2]
        figure.add_trace(
            go.Scatter3d(
                x=[0.0],
                y=[0.0],
                z=[center["validation_loss"]],
                mode="markers",
                name="final weights",
                marker={"size": 11, "color": "#ffffff", "line": {"width": 2, "color": "#1f2937"}},
            )
        )
        figure.add_trace(
            go.Scatter3d(
                x=[best["alpha"]],
                y=[best["beta"]],
                z=[best["validation_loss"]],
                mode="markers",
                name="best nearby",
                marker={"size": 8, "color": "#38bdf8", "symbol": "diamond"},
            )
        )
    figure.update_layout(
        height=460,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(7, 13, 28, 0.90)",
        font={"color": "#dbeafe"},
        scene={
            "xaxis": {"title": "direction alpha", "gridcolor": "rgba(148, 163, 184, 0.18)"},
            "yaxis": {"title": "direction beta", "gridcolor": "rgba(148, 163, 184, 0.18)"},
            "zaxis": {"title": "validation loss", "gridcolor": "rgba(148, 163, 184, 0.18)"},
            "camera": {"eye": {"x": 1.45, "y": -1.55, "z": 0.95}},
        },
        legend={"orientation": "h", "y": 1.05},
    )
    return figure


def _render_summary(config: PlaygroundConfig, result: Mapping[str, Any], *, compact: bool = False) -> None:
    summary = result.get("summary", {})
    samples = _result_frame(result, "samples", pd.DataFrame(columns=["x1", "x2", "target"]))
    grid = _result_frame(result, "grid", pd.DataFrame(columns=["x1", "x2", "probability"]))
    network_layers = _result_frame(result, "network_layers", _empty_network_layers())
    validation_accuracy = _finite_number(summary.get("validation_accuracy", 0.0))
    gap = _generalization_gap(summary)
    confidence = _confidence_score(grid)
    sample_count = _summary_sample_count(summary, samples)
    parameter_count = _parameter_count(network_layers)
    run_quality = _run_quality_label(validation_accuracy, gap)
    gap_note = _gap_quality_label(gap)
    confidence_note = _decision_confidence_note(confidence)
    validation_value = _format_percent(validation_accuracy)
    gap_value = _format_percentage_points(gap)
    confidence_value = _format_percent(confidence)
    chips = _summary_chips(
        config=config,
        samples=samples,
        parameter_count=parameter_count,
        sample_count=sample_count,
    )
    if compact:
        st.markdown(
            _compact_summary_panel(
                run_quality=run_quality,
                gap_note=gap_note,
                confidence_note=confidence_note,
                validation_value=validation_value,
                gap_value=gap_value,
                confidence_value=confidence_value,
                chips=chips,
            ),
            unsafe_allow_html=True,
        )
        return
    headline = (
        f"{run_quality}: "
        f"{gap_note}, {confidence_note}"
    )
    st.markdown(
        _summary_banner(
            headline,
            chips,
        ),
        unsafe_allow_html=True,
    )
    columns = st.columns(3)
    cards = [
        _metric_card("Validation", validation_value, "held-out accuracy"),
        _metric_card("Train-val gap", gap_value, gap_note, state=_gap_state(gap)),
        _metric_card(
            "Decision confidence",
            confidence_value,
            confidence_note,
            state="ready" if confidence >= 0.35 else "incomplete",
        ),
    ]
    for column, card in zip(columns, cards, strict=False):
        with column:
            st.markdown(card, unsafe_allow_html=True)


def main(
    *,
    config_override: PlaygroundConfig | None = None,
    preset_label: str | None = None,
    interactive_controls: bool = True,
    compute_loss_landscape: bool | None = None,
    landscape_resolution: int = 21,
    landscape_span: float = 0.75,
    evidence_dirs: Sequence[str | Path] | None = None,
    configure_page: bool = True,
    compact: bool = False,
) -> None:
    if configure_page:
        st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    render_logo()
    _render_page_styles()
    active_app = _resolve_active_app()
    shared_config = _config_from_query_params(st.query_params)

    if interactive_controls:
        with st.sidebar:
            st.markdown("### Challenge")
            preset_labels = tuple(PLAYGROUND_PRESETS)
            preset_index = 0 if shared_config is not None else preset_labels.index(DEFAULT_PRESET)
            preset_label = st.selectbox(
                "Challenge preset",
                preset_labels,
                index=preset_index,
                help="Preset only seeds the controls; every value stays editable.",
            )
            defaults = _preset_config(preset_label, shared_config)
            preset_key = _safe_key_fragment(preset_label)
            st.caption(_preset_story(preset_label, shared_config))
            st.markdown("### Dataset")
            dataset = st.selectbox("Dataset", DATASETS, index=DATASETS.index(defaults.dataset), key=f"pt_dataset_{preset_key}")
            sample_count = st.slider("Samples", 64, 1000, defaults.sample_count, step=32, key=f"pt_samples_{preset_key}")
            noise = st.slider("Noise", 0.0, 0.5, defaults.noise, step=0.01, key=f"pt_noise_{preset_key}")
            train_ratio = st.slider("Train split", 0.5, 0.95, defaults.train_ratio, step=0.05, key=f"pt_split_{preset_key}")
            feature_names = st.multiselect(
                "Features",
                FEATURES,
                default=list(defaults.feature_names),
                key=f"pt_features_{preset_key}",
            )
            st.markdown("### Network")
            hidden_raw = st.text_input(
                "Hidden layers",
                value=",".join(str(width) for width in defaults.hidden_layers),
                key=f"pt_layers_{preset_key}",
                help="Comma-separated widths, for example 16,8.",
            )
            activation = st.selectbox(
                "Activation",
                ACTIVATIONS,
                index=ACTIVATIONS.index(defaults.activation),
                key=f"pt_activation_{preset_key}",
            )
            optimizer = st.selectbox(
                "Optimizer",
                OPTIMIZERS,
                index=OPTIMIZERS.index(defaults.optimizer),
                key=f"pt_optimizer_{preset_key}",
            )
            regularization = st.selectbox(
                "Regularization",
                REGULARIZATIONS,
                index=REGULARIZATIONS.index(defaults.regularization),
                key=f"pt_regularization_{preset_key}",
            )
            regularization_rate = st.slider(
                "Regularization rate",
                0.0,
                1.0,
                defaults.regularization_rate,
                step=0.001,
                format="%.3f",
                key=f"pt_regularization_rate_{preset_key}",
                disabled=regularization == "None",
            )
            learning_rate = st.slider(
                "Learning rate",
                0.001,
                0.2,
                defaults.learning_rate,
                step=0.001,
                format="%.3f",
                key=f"pt_lr_{preset_key}",
            )
            epochs = st.slider("Epochs", 10, 300, defaults.epochs, step=10, key=f"pt_epochs_{preset_key}")
            batch_size = st.slider("Batch size", 8, 256, defaults.batch_size, step=8, key=f"pt_batch_{preset_key}")
            grid_size = st.slider("Grid resolution", 12, 120, defaults.grid_size, step=4, key=f"pt_grid_{preset_key}")
            seed = st.number_input("Seed", min_value=0, max_value=9999, value=defaults.seed, step=1, key=f"pt_seed_{preset_key}")
            st.markdown("### Run")
            train_requested = st.button("Train / refresh", type="primary", width="stretch")
            st.caption("Controls are staged. Charts and evidence update only when you train.")

        try:
            hidden_layers = _parse_hidden_layers(hidden_raw)
        except ValueError as exc:
            st.error(str(exc))
            st.stop()

        config = PlaygroundConfig(
            dataset=dataset,
            sample_count=sample_count,
            noise=noise,
            train_ratio=train_ratio,
            hidden_layers=hidden_layers,
            activation=activation,
            optimizer=optimizer,
            regularization=regularization,
            regularization_rate=regularization_rate if regularization != "None" else 0.0,
            learning_rate=learning_rate,
            epochs=epochs,
            batch_size=batch_size,
            seed=int(seed),
            feature_names=tuple(feature_names or DEFAULT_FEATURES),
            grid_size=grid_size,
        )
        shared_signature = _config_signature(shared_config) if shared_config is not None else ""
        previous_shared_signature = str(_session_state_get(SHARED_CONFIG_SIGNATURE_STATE_KEY, ""))
        force_shared_refresh = bool(shared_config is not None and shared_signature != previous_shared_signature)
        _session_state_set(SHARED_CONFIG_SIGNATURE_STATE_KEY, shared_signature)
        trained_config, trained_preset, pending_changes = _resolve_trained_config(
            config,
            str(preset_label),
            train_requested=train_requested,
            force_refresh=force_shared_refresh,
        )
    else:
        evidence_result = _load_latest_evidence_result(evidence_dirs)
        if evidence_result is None:
            trained_config = config_override or PlaygroundConfig()
            _render_hero(active_app, preset_label or "ORCHESTRATE args", trained_config)
            st.info("No exported PyTorch evidence found yet. Run the app once from ORCHESTRATE, then return to ANALYSIS.")
            return
        trained_config, result, evidence_root = evidence_result
        trained_preset = preset_label or "Latest ORCHESTRATE evidence"
        pending_changes = False
        if not compact:
            st.caption(f"Loaded evidence from `{evidence_root}`.")

    trained_config_dict = asdict(trained_config)
    if interactive_controls:
        result = _cached_train(trained_config_dict)
    if interactive_controls:
        with st.sidebar:
            st.caption(f"Charts show: {trained_preset}")
            if pending_changes:
                st.warning("Pending changes. Press Train / refresh to update the run.")
    if compact:
        _render_compact_header(active_app, trained_preset, trained_config)
    else:
        _render_hero(active_app, trained_preset, trained_config)
    if not interactive_controls and not compact:
        st.caption("Charts use the persisted ORCHESTRATE arguments for this app.")
    if result["status"] == "missing_torch":
        st.error(result["detail"])
    elif result["status"] != "ok":
        st.error(str(result.get("detail", "PyTorch training failed.")))
    if pending_changes:
        st.warning("Controls changed. The visible charts and evidence still show the last trained run.")

    _render_summary(trained_config, result, compact=compact)
    if not compact:
        _render_guided_flow(pending_changes=pending_changes, result_status=str(result.get("status", "")))
        _render_interpretation_cards(result)
        if result["status"] == "ok":
            _render_experiment_coach(trained_config, result)
    loaded_landscape = _result_frame(result, "loss_landscape", _empty_loss_landscape())
    landscape_result: dict[str, Any] = {
        "status": "not_computed",
        "detail": "",
        "loss_landscape": loaded_landscape,
        "landscape_summary": result.get("landscape_summary", _loss_landscape_summary(loaded_landscape)),
    }
    decision_tab, activations_tab, landscape_tab, evidence_tab = st.tabs(
        ["Boundary lab", "Neuron lens", "Loss terrain", "Evidence pack"]
    )
    with decision_tab:
        _render_section_intro(
            "Decision boundary",
            "The bright contour is the 0.5 frontier; points show the training sample classes.",
        )
        left, right = st.columns([2, 1])
        with left:
            visible_grid = _boundary_snapshot_grid(result, result["grid"])
            st.plotly_chart(
                _decision_figure(result["samples"], visible_grid, trained_config.grid_size),
                width="stretch",
                config={"displayModeBar": False},
            )
        with right:
            st.plotly_chart(
                _history_figure(result["history"]),
                width="stretch",
                config={"displayModeBar": False},
            )
            st.dataframe(result["history"].tail(8), width="stretch", hide_index=True)

    with activations_tab:
        network_layers = _result_frame(result, "network_layers", _empty_network_layers())
        activation_maps = _result_frame(result, "activation_maps", _empty_activation_maps())
        _render_section_intro(
            "Network internals",
            "Compare layer weight magnitudes, then inspect one hidden neuron activation map at a time.",
        )
        st.markdown(_network_architecture_html(trained_config, network_layers), unsafe_allow_html=True)
        st.plotly_chart(_network_figure(network_layers), width="stretch", config={"displayModeBar": False})
        st.dataframe(network_layers, width="stretch", hide_index=True)
        if activation_maps.empty:
            st.info("Hidden activation maps are available after a PyTorch run with at least one hidden layer.")
        else:
            controls, chart_area = st.columns([1, 3])
            with controls:
                layer_options = sorted(int(value) for value in activation_maps["layer"].unique())
                selected_layer = st.selectbox("Layer", layer_options)
                layer_maps = activation_maps[activation_maps["layer"] == selected_layer]
                neuron_options = sorted(int(value) for value in layer_maps["neuron"].unique())
                selected_neuron = st.selectbox("Neuron", neuron_options)
                selected = layer_maps[layer_maps["neuron"] == selected_neuron]["activation"]
                st.metric("Mean", f"{selected.mean():.3f}")
                st.metric("Range", f"{selected.min():.3f} / {selected.max():.3f}")
            with chart_area:
                st.plotly_chart(
                    _activation_figure(activation_maps, selected_layer, selected_neuron),
                    width="stretch",
                    config={"displayModeBar": False},
                )

    with landscape_tab:
        _render_section_intro(
            "Loss terrain",
            "Compute a deterministic 3D projection around the final weights to see whether the solution sits in a valley.",
        )
        controls, chart_area = st.columns([1, 3])
        with controls:
            if interactive_controls:
                landscape_resolution = st.slider("Resolution", 5, 31, 21, step=2)
                landscape_span = st.slider("Span", 0.1, 1.5, 0.75, step=0.05)
                compute_landscape = st.checkbox("Compute landscape", value=False)
            else:
                compute_landscape = bool(compute_loss_landscape)
                st.metric("Resolution", int(landscape_resolution))
                st.metric("Span", f"{float(landscape_span):.2f}")
        if result["status"] != "ok":
            st.info("Loss landscape is available after a successful PyTorch run.")
        elif compute_landscape:
            if interactive_controls:
                landscape_result = _cached_loss_landscape(
                    trained_config_dict,
                    int(landscape_resolution),
                    float(landscape_span),
                )
            landscape = _result_frame(landscape_result, "loss_landscape", _empty_loss_landscape())
            summary = landscape_result.get("landscape_summary", _loss_landscape_summary(landscape))
            with controls:
                st.metric("Points", summary.get("points", 0))
                st.metric("Sharpness", f"{summary.get('sharpness', 0.0):.3f}")
                st.metric("Best delta", f"{summary.get('best_delta', 0.0):.3f}")
            with chart_area:
                st.plotly_chart(
                    _loss_landscape_figure(landscape),
                    width="stretch",
                    config={"displayModeBar": False},
                )
                st.dataframe(landscape.sort_values("validation_loss").head(8), width="stretch", hide_index=True)
        else:
            if interactive_controls:
                st.info("Enable computation to evaluate a deterministic 2D loss projection around the trained weights.")
            else:
                st.info("Enable Loss landscape in ORCHESTRATE to evaluate a deterministic 2D projection.")

    with evidence_tab:
        _render_section_intro(
            "Evidence export",
            "Download the deterministic ZIP or copy the query token to replay the same playground configuration.",
        )
        evidence_result = dict(result)
        landscape = _result_frame(landscape_result, "loss_landscape", _empty_loss_landscape())
        if not landscape.empty:
            evidence_result["loss_landscape"] = landscape
            evidence_result["landscape_summary"] = landscape_result.get("landscape_summary", _loss_landscape_summary(landscape))
        manifest = _build_evidence_manifest(trained_config, evidence_result)
        st.download_button(
            "Download evidence pack",
            data=_build_evidence_pack(trained_config, evidence_result),
            file_name="pytorch_playground_evidence.zip",
            mime="application/zip",
        )
        st.code(f"?pytorch_playground={_encode_share_config(trained_config)}", language="text")
        st.code(json.dumps(_json_safe(manifest), indent=2, sort_keys=True), language="json")


if __name__ == "__main__":
    main()
