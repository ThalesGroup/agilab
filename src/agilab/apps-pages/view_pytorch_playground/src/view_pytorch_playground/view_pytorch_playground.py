# BSD 3-Clause License
#
# Copyright (c) 2026, Jean-Pierre Morard, THALES SIX GTS France SAS

from __future__ import annotations

import argparse
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


def _train_playground(config: PlaygroundConfig) -> dict[str, Any]:
    samples = _make_dataset(config)
    if torch is None or nn is None:
        return {
            "status": "missing_torch",
            "detail": "Install the page bundle dependencies to enable PyTorch training.",
            "samples": samples,
            "history": pd.DataFrame(columns=["epoch", "train_loss", "validation_loss", "train_accuracy", "validation_accuracy"]),
            "grid": pd.DataFrame(columns=["x1", "x2", "probability"]),
            "summary": {
                "backend": "missing",
                "samples": int(len(samples)),
                "features": int(len(config.feature_names)),
            },
        }

    torch.manual_seed(config.seed)
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

    model = _build_model(features.shape[1], config)
    loss_fn = nn.CrossEntropyLoss()
    if config.optimizer == "SGD":
        optimizer = torch.optim.SGD(model.parameters(), lr=config.learning_rate)
    else:
        optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)

    history_rows: list[dict[str, float | int]] = []
    epochs = max(1, int(config.epochs))
    batch_size = max(4, min(int(config.batch_size), len(train_indices)))
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

    grid = _decision_grid(model, config, mean, std)
    history = pd.DataFrame(history_rows)
    final = history.iloc[-1].to_dict() if not history.empty else {}
    return {
        "status": "ok",
        "detail": "",
        "samples": samples,
        "history": history,
        "grid": grid,
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
        train_logits = model(x_train)
        validation_logits = model(x_validation)
        train_loss = loss_fn(train_logits, y_train).item()
        validation_loss = loss_fn(validation_logits, y_validation).item()
        train_accuracy = (train_logits.argmax(dim=1) == y_train).float().mean().item()
        validation_accuracy = (validation_logits.argmax(dim=1) == y_validation).float().mean().item()
    rows.append(
        {
            "epoch": int(epoch),
            "train_loss": float(train_loss),
            "validation_loss": float(validation_loss),
            "train_accuracy": float(train_accuracy),
            "validation_accuracy": float(validation_accuracy),
        }
    )


def _decision_grid(model, config: PlaygroundConfig, mean: np.ndarray, std: np.ndarray) -> pd.DataFrame:
    axis = np.linspace(-1.35, 1.35, max(12, int(config.grid_size)))
    xx, yy = np.meshgrid(axis, axis)
    grid_points = pd.DataFrame({"x1": xx.ravel(), "x2": yy.ravel()})
    grid_features = (_feature_matrix(grid_points, config.feature_names) - mean) / std
    model.eval()
    with torch.no_grad():
        logits = model(torch.tensor(grid_features, dtype=torch.float32))
        probabilities = torch.softmax(logits, dim=1)[:, 1].cpu().numpy()
    grid_points["probability"] = probabilities.astype(float)
    return grid_points


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


def _decision_figure(samples: pd.DataFrame, grid: pd.DataFrame, grid_size: int) -> go.Figure:
    figure = go.Figure()
    if not grid.empty:
        z = grid["probability"].to_numpy().reshape((grid_size, grid_size))
        axis = np.linspace(-1.35, 1.35, grid_size)
        figure.add_trace(
            go.Contour(
                x=axis,
                y=axis,
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
        figure.add_trace(go.Scatter(x=history["epoch"], y=history["train_loss"], mode="lines", name="train loss"))
        figure.add_trace(go.Scatter(x=history["epoch"], y=history["validation_loss"], mode="lines", name="validation loss"))
        figure.add_trace(go.Scatter(x=history["epoch"], y=history["train_accuracy"], mode="lines", name="train accuracy"))
        figure.add_trace(go.Scatter(x=history["epoch"], y=history["validation_accuracy"], mode="lines", name="validation accuracy"))
    figure.update_layout(height=280, margin={"l": 12, "r": 12, "t": 12, "b": 12}, yaxis={"range": [0, 1.05]})
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
    st.title(PAGE_TITLE)
    if active_app is not None:
        st.caption(active_app.name)

    with st.sidebar:
        dataset = st.selectbox("Dataset", DATASETS, index=0)
        sample_count = st.slider("Samples", 64, 1000, 256, step=32)
        noise = st.slider("Noise", 0.0, 0.5, 0.12, step=0.01)
        feature_names = st.multiselect("Features", FEATURES, default=list(DEFAULT_FEATURES))
        hidden_raw = st.text_input("Hidden layers", value="8,8")
        activation = st.selectbox("Activation", ACTIVATIONS, index=0)
        optimizer = st.selectbox("Optimizer", OPTIMIZERS, index=0)
        learning_rate = st.slider("Learning rate", 0.001, 0.2, 0.03, step=0.001, format="%.3f")
        epochs = st.slider("Epochs", 10, 300, 80, step=10)
        batch_size = st.slider("Batch size", 8, 256, 32, step=8)
        seed = st.number_input("Seed", min_value=0, max_value=9999, value=7, step=1)

    try:
        hidden_layers = _parse_hidden_layers(hidden_raw)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    config = PlaygroundConfig(
        dataset=dataset,
        sample_count=sample_count,
        noise=noise,
        hidden_layers=hidden_layers,
        activation=activation,
        optimizer=optimizer,
        learning_rate=learning_rate,
        epochs=epochs,
        batch_size=batch_size,
        seed=int(seed),
        feature_names=tuple(feature_names or DEFAULT_FEATURES),
    )
    result = _cached_train(asdict(config))
    if result["status"] == "missing_torch":
        st.error(result["detail"])

    _render_summary(result["summary"])
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


if __name__ == "__main__":
    main()
