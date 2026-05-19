# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import io
import json
import zipfile
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import sys
from typing import Any

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

try:  # pragma: no cover - exercised conditionally in environments with torch
    import torch
    from torch import nn
except Exception:  # pragma: no cover - lightweight environments may omit torch
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]


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

from agi_gui.pagelib import render_logo


PAGE_TITLE = "PyTorch playground"
DATASETS = ("circles", "xor", "spiral", "gaussian")
FEATURES = (
    "x1",
    "x2",
    "x1_squared",
    "x2_squared",
    "x1_x2",
    "sin_x1",
    "sin_x2",
)
DEFAULT_FEATURES = ("x1", "x2", "x1_squared", "x2_squared", "x1_x2")
ACTIVATIONS = ("tanh", "relu", "sigmoid", "identity")
OPTIMIZERS = ("Adam", "SGD")
CONFIG_SCHEMA = "agilab.pytorch_playground_config.v1"
EVIDENCE_SCHEMA = "agilab.pytorch_playground_evidence.v1"
ZIP_TIMESTAMP = (2026, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class PlaygroundConfig:
    dataset: str = "circles"
    sample_count: int = 256
    noise: float = 0.12
    train_ratio: float = 0.75
    hidden_layers: tuple[int, ...] = (8, 8)
    activation: str = "tanh"
    optimizer: str = "Adam"
    learning_rate: float = 0.03
    epochs: int = 80
    batch_size: int = 32
    seed: int = 7
    feature_names: tuple[str, ...] = DEFAULT_FEATURES
    grid_size: int = 80


def _resolve_active_app() -> Path | None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--active-app", dest="active_app", type=str)
    args, _ = parser.parse_known_args()
    if not args.active_app:
        return None
    active_app = Path(args.active_app).expanduser().resolve()
    return active_app if active_app.exists() else None


def _parse_hidden_layers(raw: str) -> tuple[int, ...]:
    cleaned = raw.strip()
    if not cleaned:
        return ()
    values: list[int] = []
    for token in re.split(r"[,\s;]+", cleaned):
        if not token:
            continue
        try:
            width = int(token)
        except ValueError as exc:
            raise ValueError(f"Hidden layer width must be an integer: {token}") from exc
        if width < 1 or width > 256:
            raise ValueError("Hidden layer widths must be between 1 and 256.")
        values.append(width)
    if len(values) > 6:
        raise ValueError("Use at most six hidden layers.")
    return tuple(values)


def _bounded_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not np.isfinite(number):
        return default
    return float(max(minimum, min(maximum, number)))


def _coerce_hidden_layers(value: Any, default: tuple[int, ...] = (8, 8)) -> tuple[int, ...]:
    if isinstance(value, str):
        try:
            return _parse_hidden_layers(value)
        except ValueError:
            return default
    if isinstance(value, (list, tuple)):
        try:
            return _parse_hidden_layers(",".join(str(item) for item in value))
        except ValueError:
            return default
    return default


def _coerce_feature_names(value: Any, default: tuple[str, ...] = DEFAULT_FEATURES) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = [token.strip() for token in value.split(",")]
    elif isinstance(value, (list, tuple)):
        raw_values = [str(token).strip() for token in value]
    else:
        raw_values = list(default)
    selected = tuple(name for name in raw_values if name in FEATURES)
    return selected or default


def _config_payload(config: PlaygroundConfig) -> dict[str, Any]:
    payload = asdict(config)
    payload["hidden_layers"] = list(config.hidden_layers)
    payload["feature_names"] = list(config.feature_names)
    return {"schema": CONFIG_SCHEMA, "config": payload}


def _config_from_payload(payload: Mapping[str, Any]) -> PlaygroundConfig:
    raw_config = payload.get("config", payload)
    if not isinstance(raw_config, Mapping):
        raw_config = {}
    default = PlaygroundConfig()
    dataset = str(raw_config.get("dataset", default.dataset))
    activation = str(raw_config.get("activation", default.activation))
    optimizer = str(raw_config.get("optimizer", default.optimizer))
    return PlaygroundConfig(
        dataset=dataset if dataset in DATASETS else default.dataset,
        sample_count=_bounded_int(raw_config.get("sample_count"), default=default.sample_count, minimum=64, maximum=1000),
        noise=_bounded_float(raw_config.get("noise"), default=default.noise, minimum=0.0, maximum=0.5),
        train_ratio=_bounded_float(raw_config.get("train_ratio"), default=default.train_ratio, minimum=0.5, maximum=0.95),
        hidden_layers=_coerce_hidden_layers(raw_config.get("hidden_layers"), default.hidden_layers),
        activation=activation if activation in ACTIVATIONS else default.activation,
        optimizer=optimizer if optimizer in OPTIMIZERS else default.optimizer,
        learning_rate=_bounded_float(raw_config.get("learning_rate"), default=default.learning_rate, minimum=0.001, maximum=0.2),
        epochs=_bounded_int(raw_config.get("epochs"), default=default.epochs, minimum=10, maximum=300),
        batch_size=_bounded_int(raw_config.get("batch_size"), default=default.batch_size, minimum=8, maximum=256),
        seed=_bounded_int(raw_config.get("seed"), default=default.seed, minimum=0, maximum=9999),
        feature_names=_coerce_feature_names(raw_config.get("feature_names"), default.feature_names),
        grid_size=_bounded_int(raw_config.get("grid_size"), default=default.grid_size, minimum=12, maximum=120),
    )


def _encode_share_config(config: PlaygroundConfig) -> str:
    raw = json.dumps(_config_payload(config), sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_share_config(raw: str) -> PlaygroundConfig | None:
    if not raw:
        return None
    try:
        padding = "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode((raw + padding).encode("ascii")).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    return _config_from_payload(payload)


def _first_query_value(value: Any) -> str | None:
    if isinstance(value, (list, tuple)):
        if not value:
            return None
        value = value[0]
    if value is None:
        return None
    return str(value)


def _config_from_query_params(params: Mapping[str, Any]) -> PlaygroundConfig | None:
    for key in ("pytorch_playground", "config"):
        token = _first_query_value(params.get(key))
        decoded = _decode_share_config(token or "")
        if decoded is not None:
            return decoded
    return None


def _make_dataset(config: PlaygroundConfig) -> pd.DataFrame:
    rng = np.random.default_rng(config.seed)
    count = max(16, int(config.sample_count))
    dataset = config.dataset if config.dataset in DATASETS else "circles"
    noise = max(0.0, float(config.noise))

    if dataset == "xor":
        points = rng.uniform(-1.0, 1.0, size=(count, 2))
        points += rng.normal(0.0, noise, size=points.shape)
        labels = (points[:, 0] * points[:, 1] < 0.0).astype(int)
    elif dataset == "spiral":
        points, labels = _make_spiral_dataset(rng, count, noise)
    elif dataset == "gaussian":
        points, labels = _make_gaussian_dataset(rng, count, noise)
    else:
        points, labels = _make_circle_dataset(rng, count, noise)

    order = rng.permutation(len(labels))
    frame = pd.DataFrame(
        {
            "x1": points[order, 0].astype(float),
            "x2": points[order, 1].astype(float),
            "target": labels[order].astype(int),
        }
    )
    return frame.reset_index(drop=True)


def _make_circle_dataset(
    rng: np.random.Generator,
    count: int,
    noise: float,
) -> tuple[np.ndarray, np.ndarray]:
    inner_count = count // 2
    outer_count = count - inner_count
    inner_theta = rng.uniform(0.0, 2.0 * np.pi, size=inner_count)
    outer_theta = rng.uniform(0.0, 2.0 * np.pi, size=outer_count)
    inner_radius = 0.42 + rng.normal(0.0, noise, size=inner_count)
    outer_radius = 0.95 + rng.normal(0.0, noise, size=outer_count)
    inner = np.column_stack((inner_radius * np.cos(inner_theta), inner_radius * np.sin(inner_theta)))
    outer = np.column_stack((outer_radius * np.cos(outer_theta), outer_radius * np.sin(outer_theta)))
    points = np.vstack((inner, outer))
    labels = np.concatenate((np.zeros(inner_count, dtype=int), np.ones(outer_count, dtype=int)))
    return points, labels


def _make_spiral_dataset(
    rng: np.random.Generator,
    count: int,
    noise: float,
) -> tuple[np.ndarray, np.ndarray]:
    first_count = count // 2
    second_count = count - first_count
    points_by_class: list[np.ndarray] = []
    labels_by_class: list[np.ndarray] = []
    for class_id, class_count in enumerate((first_count, second_count)):
        radius = np.linspace(0.12, 1.0, class_count)
        theta = class_id * np.pi + 4.2 * radius + rng.normal(0.0, noise * 2.0, size=class_count)
        points = np.column_stack((radius * np.cos(theta), radius * np.sin(theta)))
        points += rng.normal(0.0, noise * 0.35, size=points.shape)
        points_by_class.append(points)
        labels_by_class.append(np.full(class_count, class_id, dtype=int))
    return np.vstack(points_by_class), np.concatenate(labels_by_class)


def _make_gaussian_dataset(
    rng: np.random.Generator,
    count: int,
    noise: float,
) -> tuple[np.ndarray, np.ndarray]:
    first_count = count // 2
    second_count = count - first_count
    spread = 0.24 + noise
    first = rng.normal(loc=(-0.45, -0.25), scale=spread, size=(first_count, 2))
    second = rng.normal(loc=(0.45, 0.30), scale=spread, size=(second_count, 2))
    points = np.vstack((first, second))
    labels = np.concatenate((np.zeros(first_count, dtype=int), np.ones(second_count, dtype=int)))
    return points, labels


def _feature_matrix(samples: pd.DataFrame | np.ndarray, feature_names: tuple[str, ...]) -> np.ndarray:
    if isinstance(samples, pd.DataFrame):
        x1 = samples["x1"].to_numpy(dtype=float)
        x2 = samples["x2"].to_numpy(dtype=float)
    else:
        points = np.asarray(samples, dtype=float)
        x1 = points[:, 0]
        x2 = points[:, 1]

    values_by_name = {
        "x1": x1,
        "x2": x2,
        "x1_squared": x1**2,
        "x2_squared": x2**2,
        "x1_x2": x1 * x2,
        "sin_x1": np.sin(np.pi * x1),
        "sin_x2": np.sin(np.pi * x2),
    }
    selected = [name for name in feature_names if name in values_by_name]
    if not selected:
        selected = ["x1", "x2"]
    return np.column_stack([values_by_name[name] for name in selected]).astype(np.float32)


def _activation_module(name: str):
    if nn is None:
        raise RuntimeError("PyTorch is not available.")
    if name == "relu":
        return nn.ReLU()
    if name == "sigmoid":
        return nn.Sigmoid()
    if name == "identity":
        return nn.Identity()
    return nn.Tanh()


def _build_model(input_dim: int, config: PlaygroundConfig):
    if nn is None:
        raise RuntimeError("PyTorch is not available.")
    layers: list[Any] = []
    previous_dim = input_dim
    for width in config.hidden_layers:
        layers.append(nn.Linear(previous_dim, width))
        layers.append(_activation_module(config.activation))
        previous_dim = width
    layers.append(nn.Linear(previous_dim, 2))
    return nn.Sequential(*layers)


def _empty_network_layers() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "layer",
            "kind",
            "input_features",
            "output_features",
            "parameters",
            "weight_mean",
            "weight_std",
            "weight_max_abs",
            "bias_mean",
            "bias_std",
            "bias_max_abs",
        ]
    )


def _empty_activation_maps() -> pd.DataFrame:
    return pd.DataFrame(columns=["layer", "neuron", "x1", "x2", "activation"])


def _empty_loss_landscape() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "alpha",
            "beta",
            "train_loss",
            "validation_loss",
            "train_accuracy",
            "validation_accuracy",
            "is_center",
        ]
    )


def _array_stats(values: np.ndarray) -> dict[str, float]:
    flattened = np.asarray(values, dtype=float).ravel()
    if flattened.size == 0:
        return {"mean": 0.0, "std": 0.0, "max_abs": 0.0}
    return {
        "mean": float(np.mean(flattened)),
        "std": float(np.std(flattened)),
        "max_abs": float(np.max(np.abs(flattened))),
    }


def _network_layers(model) -> pd.DataFrame:
    if nn is None:
        return _empty_network_layers()
    linear_layers = [layer for layer in model if isinstance(layer, nn.Linear)]
    rows: list[dict[str, Any]] = []
    for index, layer in enumerate(linear_layers):
        weight = layer.weight.detach().cpu().numpy()
        bias = layer.bias.detach().cpu().numpy() if layer.bias is not None else np.array([], dtype=float)
        weight_stats = _array_stats(weight)
        bias_stats = _array_stats(bias)
        rows.append(
            {
                "layer": index + 1,
                "kind": "output" if index == len(linear_layers) - 1 else "hidden",
                "input_features": int(layer.in_features),
                "output_features": int(layer.out_features),
                "parameters": int(weight.size + bias.size),
                "weight_mean": weight_stats["mean"],
                "weight_std": weight_stats["std"],
                "weight_max_abs": weight_stats["max_abs"],
                "bias_mean": bias_stats["mean"],
                "bias_std": bias_stats["std"],
                "bias_max_abs": bias_stats["max_abs"],
            }
        )
    return pd.DataFrame(rows, columns=_empty_network_layers().columns)


def _grid_points(config: PlaygroundConfig) -> pd.DataFrame:
    axis = np.linspace(-1.35, 1.35, max(12, int(config.grid_size)))
    xx, yy = np.meshgrid(axis, axis)
    return pd.DataFrame({"x1": xx.ravel(), "x2": yy.ravel()})


def _hidden_activation_maps(
    model,
    config: PlaygroundConfig,
    mean: np.ndarray,
    std: np.ndarray,
    *,
    max_neurons: int = 8,
) -> pd.DataFrame:
    if torch is None or nn is None or not config.hidden_layers:
        return _empty_activation_maps()

    grid_points = _grid_points(config)
    grid_features = (_feature_matrix(grid_points, config.feature_names) - mean) / std
    activation_frames: list[pd.DataFrame] = []
    hidden_layer_index = 0
    pending_hidden_layer = False

    model.eval()
    with torch.no_grad():
        values = torch.tensor(grid_features, dtype=torch.float32)
        for layer in model:
            values = layer(values)
            if isinstance(layer, nn.Linear):
                pending_hidden_layer = hidden_layer_index < len(config.hidden_layers)
                continue
            if not pending_hidden_layer:
                continue

            activations = values.detach().cpu().numpy()
            neuron_count = min(activations.shape[1], max(1, int(max_neurons)))
            for neuron_index in range(neuron_count):
                frame = grid_points.copy()
                frame.insert(0, "neuron", neuron_index + 1)
                frame.insert(0, "layer", hidden_layer_index + 1)
                frame["activation"] = activations[:, neuron_index].astype(float)
                activation_frames.append(frame)
            hidden_layer_index += 1
            pending_hidden_layer = False

    if not activation_frames:
        return _empty_activation_maps()
    return pd.concat(activation_frames, ignore_index=True)


def _prepare_training_data(config: PlaygroundConfig) -> dict[str, Any]:
    samples = _make_dataset(config)
    features = _feature_matrix(samples, config.feature_names)
    labels = samples["target"].to_numpy(dtype=np.int64)
    rng = np.random.default_rng(config.seed + 101)
    indices = rng.permutation(len(labels))
    train_count = min(len(labels) - 1, max(2, int(round(len(labels) * config.train_ratio))))
    train_indices = indices[:train_count]
    validation_indices = indices[train_count:]
    if len(validation_indices) == 0:
        validation_indices = train_indices

    mean = features[train_indices].mean(axis=0, keepdims=True)
    std = features[train_indices].std(axis=0, keepdims=True)
    std[std < 1e-6] = 1.0
    features = (features - mean) / std

    x_train = torch.tensor(features[train_indices], dtype=torch.float32)
    y_train = torch.tensor(labels[train_indices], dtype=torch.long)
    x_validation = torch.tensor(features[validation_indices], dtype=torch.float32)
    y_validation = torch.tensor(labels[validation_indices], dtype=torch.long)
    return {
        "samples": samples,
        "features": features,
        "labels": labels,
        "train_indices": train_indices,
        "validation_indices": validation_indices,
        "mean": mean,
        "std": std,
        "x_train": x_train,
        "y_train": y_train,
        "x_validation": x_validation,
        "y_validation": y_validation,
    }


def _classification_metrics(model, loss_fn, x_values, y_values) -> dict[str, float]:
    logits = model(x_values)
    loss = loss_fn(logits, y_values).item()
    accuracy = (logits.argmax(dim=1) == y_values).float().mean().item()
    return {"loss": float(loss), "accuracy": float(accuracy)}


def _fit_model(config: PlaygroundConfig, training_data: Mapping[str, Any]) -> tuple[Any, Any, pd.DataFrame]:
    features = training_data["features"]
    x_train = training_data["x_train"]
    y_train = training_data["y_train"]
    x_validation = training_data["x_validation"]
    y_validation = training_data["y_validation"]
    model = _build_model(features.shape[1], config)
    loss_fn = nn.CrossEntropyLoss()
    if config.optimizer == "SGD":
        optimizer = torch.optim.SGD(model.parameters(), lr=config.learning_rate)
    else:
        optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)

    history_rows: list[dict[str, float | int]] = []
    epochs = max(1, int(config.epochs))
    batch_size = max(4, min(int(config.batch_size), len(x_train)))
    log_every = max(1, epochs // 40)

    _append_history_row(history_rows, model, loss_fn, x_train, y_train, x_validation, y_validation, 0)
    for epoch in range(1, epochs + 1):
        model.train()
        batch_order = torch.randperm(len(x_train))
        for start in range(0, len(x_train), batch_size):
            batch_indices = batch_order[start : start + batch_size]
            optimizer.zero_grad()
            batch_logits = model(x_train[batch_indices])
            batch_loss = loss_fn(batch_logits, y_train[batch_indices])
            batch_loss.backward()
            optimizer.step()

        if epoch == epochs or epoch % log_every == 0:
            _append_history_row(history_rows, model, loss_fn, x_train, y_train, x_validation, y_validation, epoch)

    return model, loss_fn, pd.DataFrame(history_rows)


def _train_playground(config: PlaygroundConfig) -> dict[str, Any]:
    if torch is None or nn is None:
        samples = _make_dataset(config)
        return {
            "status": "missing_torch",
            "detail": "Install the page bundle dependencies to enable PyTorch training.",
            "samples": samples,
            "history": pd.DataFrame(columns=["epoch", "train_loss", "validation_loss", "train_accuracy", "validation_accuracy"]),
            "grid": pd.DataFrame(columns=["x1", "x2", "probability"]),
            "network_layers": _empty_network_layers(),
            "activation_maps": _empty_activation_maps(),
            "summary": {
                "backend": "missing",
                "samples": int(len(samples)),
                "features": int(len(config.feature_names)),
            },
        }

    torch.manual_seed(config.seed)
    training_data = _prepare_training_data(config)
    samples = training_data["samples"]
    features = training_data["features"]
    mean = training_data["mean"]
    std = training_data["std"]
    model, _loss_fn, history = _fit_model(config, training_data)
    grid = _decision_grid(model, config, mean, std)
    network_layers = _network_layers(model)
    activation_maps = _hidden_activation_maps(model, config, mean, std)
    final = history.iloc[-1].to_dict() if not history.empty else {}
    return {
        "status": "ok",
        "detail": "",
        "samples": samples,
        "history": history,
        "grid": grid,
        "network_layers": network_layers,
        "activation_maps": activation_maps,
        "summary": {
            "backend": "torch",
            "samples": int(len(samples)),
            "features": int(features.shape[1]),
            "hidden_layers": list(config.hidden_layers),
            "train_accuracy": float(final.get("train_accuracy", 0.0)),
            "validation_accuracy": float(final.get("validation_accuracy", 0.0)),
            "validation_loss": float(final.get("validation_loss", 0.0)),
        },
    }


def _append_history_row(
    rows: list[dict[str, float | int]],
    model,
    loss_fn,
    x_train,
    y_train,
    x_validation,
    y_validation,
    epoch: int,
) -> None:
    model.eval()
    with torch.no_grad():
        train_metrics = _classification_metrics(model, loss_fn, x_train, y_train)
        validation_metrics = _classification_metrics(model, loss_fn, x_validation, y_validation)
    rows.append(
        {
            "epoch": int(epoch),
            "train_loss": train_metrics["loss"],
            "validation_loss": validation_metrics["loss"],
            "train_accuracy": train_metrics["accuracy"],
            "validation_accuracy": validation_metrics["accuracy"],
        }
    )


def _decision_grid(model, config: PlaygroundConfig, mean: np.ndarray, std: np.ndarray) -> pd.DataFrame:
    grid_points = _grid_points(config)
    grid_features = (_feature_matrix(grid_points, config.feature_names) - mean) / std
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(grid_features, dtype=torch.float32))
        probabilities = torch.softmax(logits, dim=1)[:, 1].cpu().numpy()
    grid_points["probability"] = probabilities.astype(float)
    return grid_points


def _model_state_vector(model):
    return torch.cat([parameter.detach().flatten().cpu() for parameter in model.parameters()])


def _assign_model_state_vector(model, vector) -> None:
    offset = 0
    for parameter in model.parameters():
        item_count = parameter.numel()
        values = vector[offset : offset + item_count].reshape(parameter.shape).to(parameter.device, dtype=parameter.dtype)
        parameter.data.copy_(values)
        offset += item_count


def _landscape_directions(center, seed: int) -> tuple[Any, Any]:
    generator = torch.Generator()
    generator.manual_seed(int(seed) + 7001)
    first = torch.randn(center.shape, generator=generator, dtype=center.dtype)
    second = torch.randn(center.shape, generator=generator, dtype=center.dtype)
    first_norm = first.norm().clamp_min(1e-12)
    first = first / first_norm
    second = second - torch.dot(second, first) * first
    second_norm = second.norm().clamp_min(1e-12)
    second = second / second_norm
    scale = center.norm().clamp_min(1.0)
    return first * scale, second * scale


def _normalized_landscape_resolution(value: int) -> int:
    resolution = max(5, min(31, int(value)))
    if resolution % 2 == 0:
        resolution += 1
    return resolution


def _loss_landscape_summary(landscape: pd.DataFrame) -> dict[str, Any]:
    if landscape.empty:
        return {"status": "not_computed", "points": 0}
    center_candidates = landscape[landscape["is_center"]]
    center = center_candidates.iloc[0] if not center_candidates.empty else landscape.iloc[len(landscape) // 2]
    best = landscape.loc[landscape["validation_loss"].idxmin()]
    max_validation_loss = float(landscape["validation_loss"].max())
    center_loss = float(center["validation_loss"])
    return {
        "status": "ok",
        "points": int(len(landscape)),
        "center_validation_loss": center_loss,
        "center_train_loss": float(center["train_loss"]),
        "center_validation_accuracy": float(center["validation_accuracy"]),
        "best_validation_loss": float(best["validation_loss"]),
        "best_alpha": float(best["alpha"]),
        "best_beta": float(best["beta"]),
        "best_delta": float(best["validation_loss"] - center_loss),
        "sharpness": float(max(0.0, max_validation_loss - center_loss)),
    }


def _loss_landscape(config: PlaygroundConfig, *, resolution: int = 21, span: float = 0.75) -> dict[str, Any]:
    if torch is None or nn is None:
        return {
            "status": "missing_torch",
            "detail": "Install the page bundle dependencies to enable the loss landscape.",
            "loss_landscape": _empty_loss_landscape(),
            "landscape_summary": _loss_landscape_summary(_empty_loss_landscape()),
        }

    torch.manual_seed(config.seed)
    training_data = _prepare_training_data(config)
    model, loss_fn, _history = _fit_model(config, training_data)
    center = _model_state_vector(model)
    first_direction, second_direction = _landscape_directions(center, config.seed)
    resolution = _normalized_landscape_resolution(resolution)
    span = max(0.05, min(2.0, float(span)))
    axis = np.linspace(-span, span, resolution)
    rows: list[dict[str, float | bool]] = []

    try:
        model.eval()
        with torch.no_grad():
            for alpha in axis:
                for beta in axis:
                    candidate = center + float(alpha) * first_direction + float(beta) * second_direction
                    _assign_model_state_vector(model, candidate)
                    train_metrics = _classification_metrics(model, loss_fn, training_data["x_train"], training_data["y_train"])
                    validation_metrics = _classification_metrics(
                        model,
                        loss_fn,
                        training_data["x_validation"],
                        training_data["y_validation"],
                    )
                    rows.append(
                        {
                            "alpha": float(alpha),
                            "beta": float(beta),
                            "train_loss": train_metrics["loss"],
                            "validation_loss": validation_metrics["loss"],
                            "train_accuracy": train_metrics["accuracy"],
                            "validation_accuracy": validation_metrics["accuracy"],
                            "is_center": bool(np.isclose(alpha, 0.0) and np.isclose(beta, 0.0)),
                        }
                    )
    finally:
        _assign_model_state_vector(model, center)

    landscape = pd.DataFrame(rows, columns=_empty_loss_landscape().columns)
    return {
        "status": "ok",
        "detail": "",
        "loss_landscape": landscape,
        "landscape_summary": _loss_landscape_summary(landscape),
    }


@st.cache_data(show_spinner=False)
def _cached_train(payload: dict[str, Any]) -> dict[str, Any]:
    config = PlaygroundConfig(
        dataset=str(payload["dataset"]),
        sample_count=int(payload["sample_count"]),
        noise=float(payload["noise"]),
        train_ratio=float(payload["train_ratio"]),
        hidden_layers=tuple(int(value) for value in payload["hidden_layers"]),
        activation=str(payload["activation"]),
        optimizer=str(payload["optimizer"]),
        learning_rate=float(payload["learning_rate"]),
        epochs=int(payload["epochs"]),
        batch_size=int(payload["batch_size"]),
        seed=int(payload["seed"]),
        feature_names=tuple(str(value) for value in payload["feature_names"]),
        grid_size=int(payload["grid_size"]),
    )
    return _train_playground(config)


@st.cache_data(show_spinner=False)
def _cached_loss_landscape(payload: dict[str, Any], resolution: int, span: float) -> dict[str, Any]:
    config = PlaygroundConfig(
        dataset=str(payload["dataset"]),
        sample_count=int(payload["sample_count"]),
        noise=float(payload["noise"]),
        train_ratio=float(payload["train_ratio"]),
        hidden_layers=tuple(int(value) for value in payload["hidden_layers"]),
        activation=str(payload["activation"]),
        optimizer=str(payload["optimizer"]),
        learning_rate=float(payload["learning_rate"]),
        epochs=int(payload["epochs"]),
        batch_size=int(payload["batch_size"]),
        seed=int(payload["seed"]),
        feature_names=tuple(str(value) for value in payload["feature_names"]),
        grid_size=int(payload["grid_size"]),
    )
    return _loss_landscape(config, resolution=resolution, span=span)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, float):
        return value if np.isfinite(value) else None
    return value


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(_json_safe(payload), indent=2, sort_keys=True).encode("utf-8") + b"\n"


def _dataframe_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False, float_format="%.10g").encode("utf-8")


def _artifact_hash(payload: bytes) -> dict[str, Any]:
    return {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def _result_frame(result: Mapping[str, Any], key: str, empty: pd.DataFrame) -> pd.DataFrame:
    value = result.get(key)
    return value if isinstance(value, pd.DataFrame) else empty


def _evidence_artifact_files(config: PlaygroundConfig, result: Mapping[str, Any]) -> dict[str, bytes]:
    samples = _result_frame(result, "samples", pd.DataFrame(columns=["x1", "x2", "target"]))
    history = _result_frame(result, "history", pd.DataFrame(columns=["epoch", "train_loss", "validation_loss", "train_accuracy", "validation_accuracy"]))
    grid = _result_frame(result, "grid", pd.DataFrame(columns=["x1", "x2", "probability"]))
    network_layers = _result_frame(result, "network_layers", _empty_network_layers())
    activation_maps = _result_frame(result, "activation_maps", _empty_activation_maps())
    loss_landscape = _result_frame(result, "loss_landscape", _empty_loss_landscape())
    return {
        "config/playground_config.json": _json_bytes(_config_payload(config)),
        "data/samples.csv": _dataframe_csv_bytes(samples),
        "data/training_history.csv": _dataframe_csv_bytes(history),
        "data/decision_grid.csv": _dataframe_csv_bytes(grid),
        "model/network_layers.csv": _dataframe_csv_bytes(network_layers),
        "model/hidden_activation_maps.csv": _dataframe_csv_bytes(activation_maps),
        "model/loss_landscape.csv": _dataframe_csv_bytes(loss_landscape),
        "summary/run_summary.json": _json_bytes(
            {
                "schema": EVIDENCE_SCHEMA,
                "summary": result.get("summary", {}),
                "landscape_summary": result.get("landscape_summary", _loss_landscape_summary(loss_landscape)),
            }
        ),
    }


def _build_evidence_manifest(config: PlaygroundConfig, result: Mapping[str, Any]) -> dict[str, Any]:
    files = _evidence_artifact_files(config, result)
    samples = _result_frame(result, "samples", pd.DataFrame())
    history = _result_frame(result, "history", pd.DataFrame())
    grid = _result_frame(result, "grid", pd.DataFrame())
    network_layers = _result_frame(result, "network_layers", _empty_network_layers())
    activation_maps = _result_frame(result, "activation_maps", _empty_activation_maps())
    loss_landscape = _result_frame(result, "loss_landscape", _empty_loss_landscape())
    return {
        "schema": EVIDENCE_SCHEMA,
        "config_schema": CONFIG_SCHEMA,
        "page": PAGE_TITLE,
        "backend": result.get("summary", {}).get("backend", "unknown"),
        "torch_version": getattr(torch, "__version__", None) if torch is not None else None,
        "config": _config_payload(config)["config"],
        "summary": result.get("summary", {}),
        "landscape_summary": result.get("landscape_summary", _loss_landscape_summary(loss_landscape)),
        "row_counts": {
            "samples": int(len(samples)),
            "training_history": int(len(history)),
            "decision_grid": int(len(grid)),
            "network_layers": int(len(network_layers)),
            "hidden_activation_maps": int(len(activation_maps)),
            "loss_landscape": int(len(loss_landscape)),
        },
        "artifacts": {name: _artifact_hash(payload) for name, payload in sorted(files.items())},
    }


def _deterministic_zip_bytes(files: Mapping[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _build_evidence_pack(config: PlaygroundConfig, result: Mapping[str, Any]) -> bytes:
    files = _evidence_artifact_files(config, result)
    files["manifest.json"] = _json_bytes(_build_evidence_manifest(config, result))
    return _deterministic_zip_bytes(files)


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
                colorscale=[[0.0, "#2f6f9f"], [0.5, "#f6f7f8"], [1.0, "#c44e52"]],
                contours={"start": 0.0, "end": 1.0, "size": 0.1},
                opacity=0.68,
                showscale=False,
                hoverinfo="skip",
            )
        )

    colors = {0: "#2f6f9f", 1: "#c44e52"}
    for class_id, group in samples.groupby("target", sort=True):
        figure.add_trace(
            go.Scatter(
                x=group["x1"],
                y=group["x2"],
                mode="markers",
                name=f"class {class_id}",
                marker={"size": 8, "color": colors.get(int(class_id), "#4b5563"), "line": {"width": 0.5, "color": "#ffffff"}},
            )
        )
    figure.update_layout(
        height=560,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        xaxis={"range": [-1.35, 1.35], "scaleanchor": "y", "zeroline": False},
        yaxis={"range": [-1.35, 1.35], "zeroline": False},
        legend={"orientation": "h", "y": 1.02},
    )
    return figure


def _history_figure(history: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    if not history.empty:
        figure.add_trace(go.Scatter(x=history["epoch"], y=history["train_loss"], mode="lines", name="train loss", yaxis="y"))
        figure.add_trace(
            go.Scatter(x=history["epoch"], y=history["validation_loss"], mode="lines", name="validation loss", yaxis="y")
        )
        figure.add_trace(
            go.Scatter(x=history["epoch"], y=history["train_accuracy"], mode="lines", name="train accuracy", yaxis="y2")
        )
        figure.add_trace(
            go.Scatter(
                x=history["epoch"],
                y=history["validation_accuracy"],
                mode="lines",
                name="validation accuracy",
                yaxis="y2",
            )
        )
    figure.update_layout(
        height=280,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        yaxis={"title": "loss"},
        yaxis2={"title": "accuracy", "overlaying": "y", "side": "right", "range": [0, 1.05]},
    )
    return figure


def _activation_figure(activation_maps: pd.DataFrame, layer: int, neuron: int) -> go.Figure:
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
                colorscale="Viridis",
                contours={"coloring": "heatmap"},
                colorbar={"title": "activation"},
            )
        )
    figure.update_layout(
        height=420,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        xaxis={"range": [-1.35, 1.35], "scaleanchor": "y", "zeroline": False},
        yaxis={"range": [-1.35, 1.35], "zeroline": False},
    )
    return figure


def _network_figure(layers: pd.DataFrame) -> go.Figure:
    figure = go.Figure()
    if not layers.empty:
        labels = [f"{row.kind} {int(row.layer)}" for row in layers.itertuples()]
        figure.add_trace(go.Bar(x=labels, y=layers["weight_max_abs"], name="max |weight|"))
        figure.add_trace(go.Bar(x=labels, y=layers["bias_max_abs"], name="max |bias|"))
    figure.update_layout(
        height=260,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        yaxis={"title": "magnitude"},
        barmode="group",
        legend={"orientation": "h", "y": 1.08},
    )
    return figure


def _loss_landscape_figure(landscape: pd.DataFrame) -> go.Figure:
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
            go.Contour(
                x=alpha_axis,
                y=beta_axis,
                z=z,
                colorscale="Cividis",
                contours={"coloring": "heatmap"},
                colorbar={"title": "val. loss"},
            )
        )
        best = landscape.loc[landscape["validation_loss"].idxmin()]
        figure.add_trace(
            go.Scatter(
                x=[0.0],
                y=[0.0],
                mode="markers",
                name="final weights",
                marker={"size": 11, "color": "#ffffff", "line": {"width": 2, "color": "#1f2937"}},
            )
        )
        figure.add_trace(
            go.Scatter(
                x=[best["alpha"]],
                y=[best["beta"]],
                mode="markers",
                name="best nearby",
                marker={"size": 10, "color": "#e11d48", "symbol": "x"},
            )
        )
    figure.update_layout(
        height=460,
        margin={"l": 12, "r": 12, "t": 12, "b": 12},
        xaxis={"title": "direction alpha", "zeroline": True},
        yaxis={"title": "direction beta", "zeroline": True},
        legend={"orientation": "h", "y": 1.05},
    )
    return figure


def _render_summary(summary: dict[str, Any]) -> None:
    columns = st.columns(4)
    columns[0].metric("Samples", summary.get("samples", 0))
    columns[1].metric("Features", summary.get("features", 0))
    columns[2].metric("Train acc.", f"{summary.get('train_accuracy', 0.0):.2f}")
    columns[3].metric("Validation acc.", f"{summary.get('validation_accuracy', 0.0):.2f}")


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE, layout="wide")
    render_logo()
    active_app = _resolve_active_app()
    shared_config = _config_from_query_params(st.query_params)
    defaults = shared_config or PlaygroundConfig()
    st.title(PAGE_TITLE)
    if active_app is not None:
        st.caption(active_app.name)

    with st.sidebar:
        dataset = st.selectbox("Dataset", DATASETS, index=DATASETS.index(defaults.dataset))
        sample_count = st.slider("Samples", 64, 1000, defaults.sample_count, step=32)
        noise = st.slider("Noise", 0.0, 0.5, defaults.noise, step=0.01)
        train_ratio = st.slider("Train split", 0.5, 0.95, defaults.train_ratio, step=0.05)
        feature_names = st.multiselect("Features", FEATURES, default=list(defaults.feature_names))
        hidden_raw = st.text_input("Hidden layers", value=",".join(str(width) for width in defaults.hidden_layers))
        activation = st.selectbox("Activation", ACTIVATIONS, index=ACTIVATIONS.index(defaults.activation))
        optimizer = st.selectbox("Optimizer", OPTIMIZERS, index=OPTIMIZERS.index(defaults.optimizer))
        learning_rate = st.slider("Learning rate", 0.001, 0.2, defaults.learning_rate, step=0.001, format="%.3f")
        epochs = st.slider("Epochs", 10, 300, defaults.epochs, step=10)
        batch_size = st.slider("Batch size", 8, 256, defaults.batch_size, step=8)
        grid_size = st.slider("Grid resolution", 12, 120, defaults.grid_size, step=4)
        seed = st.number_input("Seed", min_value=0, max_value=9999, value=defaults.seed, step=1)

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
        learning_rate=learning_rate,
        epochs=epochs,
        batch_size=batch_size,
        seed=int(seed),
        feature_names=tuple(feature_names or DEFAULT_FEATURES),
        grid_size=grid_size,
    )
    config_dict = asdict(config)
    result = _cached_train(config_dict)
    if result["status"] == "missing_torch":
        st.error(result["detail"])

    _render_summary(result["summary"])
    landscape_result: dict[str, Any] = {
        "status": "not_computed",
        "detail": "",
        "loss_landscape": _empty_loss_landscape(),
        "landscape_summary": _loss_landscape_summary(_empty_loss_landscape()),
    }
    decision_tab, activations_tab, landscape_tab, evidence_tab = st.tabs(
        ["Decision", "Activations", "Loss landscape", "Evidence"]
    )
    with decision_tab:
        left, right = st.columns([2, 1])
        with left:
            st.plotly_chart(
                _decision_figure(result["samples"], result["grid"], config.grid_size),
                use_container_width=True,
                config={"displayModeBar": False},
            )
        with right:
            st.plotly_chart(
                _history_figure(result["history"]),
                use_container_width=True,
                config={"displayModeBar": False},
            )
            st.dataframe(result["history"].tail(8), use_container_width=True, hide_index=True)

    with activations_tab:
        network_layers = _result_frame(result, "network_layers", _empty_network_layers())
        activation_maps = _result_frame(result, "activation_maps", _empty_activation_maps())
        st.plotly_chart(_network_figure(network_layers), use_container_width=True, config={"displayModeBar": False})
        st.dataframe(network_layers, use_container_width=True, hide_index=True)
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
                    use_container_width=True,
                    config={"displayModeBar": False},
                )

    with landscape_tab:
        controls, chart_area = st.columns([1, 3])
        with controls:
            landscape_resolution = st.slider("Resolution", 5, 31, 21, step=2)
            landscape_span = st.slider("Span", 0.1, 1.5, 0.75, step=0.05)
            compute_landscape = st.checkbox("Compute landscape", value=False)
        if result["status"] != "ok":
            st.info("Loss landscape is available after a successful PyTorch run.")
        elif compute_landscape:
            landscape_result = _cached_loss_landscape(config_dict, int(landscape_resolution), float(landscape_span))
            landscape = _result_frame(landscape_result, "loss_landscape", _empty_loss_landscape())
            summary = landscape_result.get("landscape_summary", _loss_landscape_summary(landscape))
            with controls:
                st.metric("Points", summary.get("points", 0))
                st.metric("Sharpness", f"{summary.get('sharpness', 0.0):.3f}")
                st.metric("Best delta", f"{summary.get('best_delta', 0.0):.3f}")
            with chart_area:
                st.plotly_chart(
                    _loss_landscape_figure(landscape),
                    use_container_width=True,
                    config={"displayModeBar": False},
                )
                st.dataframe(landscape.sort_values("validation_loss").head(8), use_container_width=True, hide_index=True)
        else:
            st.info("Enable computation to evaluate a deterministic 2D loss projection around the trained weights.")

    with evidence_tab:
        evidence_result = dict(result)
        landscape = _result_frame(landscape_result, "loss_landscape", _empty_loss_landscape())
        if not landscape.empty:
            evidence_result["loss_landscape"] = landscape
            evidence_result["landscape_summary"] = landscape_result.get("landscape_summary", _loss_landscape_summary(landscape))
        manifest = _build_evidence_manifest(config, evidence_result)
        st.download_button(
            "Download evidence pack",
            data=_build_evidence_pack(config, evidence_result),
            file_name="pytorch_playground_evidence.zip",
            mime="application/zip",
        )
        st.code(f"?pytorch_playground={_encode_share_config(config)}", language="text")
        st.json(manifest)


if __name__ == "__main__":
    main()
