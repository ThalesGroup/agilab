"""Argument helpers for the PyTorch playground built-in app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data

DatasetName = Literal["circles", "xor", "spiral", "gaussian"]
ActivationName = Literal["tanh", "relu", "sigmoid", "identity"]
OptimizerName = Literal["Adam", "SGD"]
RegularizationName = Literal["None", "L1", "L2"]

DATASETS: tuple[DatasetName, ...] = ("circles", "xor", "spiral", "gaussian")
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
ACTIVATIONS: tuple[ActivationName, ...] = ("tanh", "relu", "sigmoid", "identity")
OPTIMIZERS: tuple[OptimizerName, ...] = ("Adam", "SGD")
REGULARIZATIONS: tuple[RegularizationName, ...] = ("None", "L1", "L2")
DEFAULT_FEATURE_NAMES = ",".join(DEFAULT_FEATURES)


class PytorchPlaygroundArgs(BaseModel):
    """Runtime parameters for the PyTorch playground app."""

    model_config = ConfigDict(extra="forbid")

    data_out: Path = Field(default_factory=lambda: Path("pytorch_playground/evidence"))
    dataset: DatasetName = "circles"
    sample_count: int = Field(default=320, ge=64, le=1000)
    noise: float = Field(default=0.08, ge=0.0, le=0.5)
    train_ratio: float = Field(default=0.75, ge=0.5, le=0.95)
    hidden_layers: str = "12,12"
    activation: ActivationName = "tanh"
    optimizer: OptimizerName = "Adam"
    regularization: RegularizationName = "None"
    regularization_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    learning_rate: float = Field(default=0.035, ge=0.001, le=0.2)
    epochs: int = Field(default=90, ge=10, le=300)
    batch_size: int = Field(default=32, ge=8, le=256)
    seed: int = Field(default=11, ge=0, le=9999)
    feature_names: str = DEFAULT_FEATURE_NAMES
    grid_size: int = Field(default=88, ge=12, le=120)
    compute_loss_landscape: bool = False
    landscape_resolution: int = Field(default=21, ge=5, le=31)
    landscape_span: float = Field(default=0.75, ge=0.1, le=1.5)
    reset_target: bool = False

    @model_validator(mode="after")
    def _normalize_text_fields(self) -> "PytorchPlaygroundArgs":
        self.hidden_layers = self.hidden_layers.strip()
        self.feature_names = ",".join(
            token.strip()
            for token in self.feature_names.split(",")
            if token.strip()
        ) or DEFAULT_FEATURE_NAMES
        return self


class PytorchPlaygroundArgsTD(TypedDict, total=False):
    data_out: str
    dataset: str
    sample_count: int
    noise: float
    train_ratio: float
    hidden_layers: str
    activation: str
    optimizer: str
    regularization: str
    regularization_rate: float
    learning_rate: float
    epochs: int
    batch_size: int
    seed: int
    feature_names: str
    grid_size: int
    compute_loss_landscape: bool
    landscape_resolution: int
    landscape_span: float
    reset_target: bool


ArgsModel = PytorchPlaygroundArgs
ArgsOverrides = PytorchPlaygroundArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> PytorchPlaygroundArgs:
    return load_model_from_toml(PytorchPlaygroundArgs, settings_path, section=section)


def merge_args(
    base: PytorchPlaygroundArgs,
    overrides: PytorchPlaygroundArgsTD | None = None,
) -> PytorchPlaygroundArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: PytorchPlaygroundArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: PytorchPlaygroundArgs, **_: Any) -> PytorchPlaygroundArgs:
    return PytorchPlaygroundArgs(**args.model_dump(mode="json"))


def coerce_feature_names(
    value: Any, default: tuple[str, ...] = DEFAULT_FEATURES
) -> tuple[str, ...]:
    if isinstance(value, str):
        raw_values = [token.strip() for token in value.split(",")]
    elif isinstance(value, (list, tuple)):
        raw_values = [str(token).strip() for token in value]
    else:
        raw_values = list(default)
    selected = tuple(name for name in raw_values if name in FEATURES)
    return selected or default


def to_playground_config(args: PytorchPlaygroundArgs):
    from .core import PlaygroundConfig, _parse_hidden_layers

    return PlaygroundConfig(
        dataset=args.dataset,
        sample_count=args.sample_count,
        noise=args.noise,
        train_ratio=args.train_ratio,
        hidden_layers=_parse_hidden_layers(args.hidden_layers),
        activation=args.activation,
        optimizer=args.optimizer,
        regularization=args.regularization,
        regularization_rate=args.regularization_rate,
        learning_rate=args.learning_rate,
        epochs=args.epochs,
        batch_size=args.batch_size,
        seed=args.seed,
        feature_names=coerce_feature_names(args.feature_names),
        grid_size=args.grid_size,
    )


__all__ = [
    "ACTIVATIONS",
    "ArgsModel",
    "ArgsOverrides",
    "DATASETS",
    "DEFAULT_FEATURES",
    "FEATURES",
    "OPTIMIZERS",
    "PytorchPlaygroundArgs",
    "PytorchPlaygroundArgsTD",
    "REGULARIZATIONS",
    "coerce_feature_names",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
    "to_playground_config",
]
