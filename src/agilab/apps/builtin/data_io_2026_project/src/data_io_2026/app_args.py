"""Argument helpers for the public Data IO 2026 demo."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class DataIo2026Args(BaseModel):
    """Runtime parameters for the autonomous mission-data decision demo."""

    model_config = ConfigDict(extra="forbid")

    data_in: Path = Field(default_factory=lambda: Path("data_io_2026/scenarios"))
    data_out: Path = Field(default_factory=lambda: Path("data_io_2026/results"))
    files: str = "*.json"
    nfile: int = Field(default=1, ge=1, le=25)
    objective: Literal["balanced_mission", "latency_first", "resilience_first"] = "balanced_mission"
    adaptation_mode: Literal["auto_replan", "observe_only"] = "auto_replan"
    failure_kind: Literal["bandwidth_drop", "node_failure", "combined"] = "bandwidth_drop"
    latency_weight: float = Field(default=0.65, ge=0.0, le=1.0)
    cost_weight: float = Field(default=0.12, ge=0.0, le=1.0)
    reliability_weight: float = Field(default=0.16, ge=0.0, le=1.0)
    risk_weight: float = Field(default=0.07, ge=0.0, le=1.0)
    random_seed: int = Field(default=2026, ge=0)
    reset_target: bool = False

    @model_validator(mode="after")
    def _validate_consistency(self) -> "DataIo2026Args":
        self.files = self.files.strip() or "*.json"
        total = (
            self.latency_weight
            + self.cost_weight
            + self.reliability_weight
            + self.risk_weight
        )
        if total <= 0:
            raise ValueError("At least one optimization weight must be positive")
        return self


class DataIo2026ArgsTD(TypedDict, total=False):
    data_in: str
    data_out: str
    files: str
    nfile: int
    objective: str
    adaptation_mode: str
    failure_kind: str
    latency_weight: float
    cost_weight: float
    reliability_weight: float
    risk_weight: float
    random_seed: int
    reset_target: bool


ArgsModel = DataIo2026Args
ArgsOverrides = DataIo2026ArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> DataIo2026Args:
    return load_model_from_toml(DataIo2026Args, settings_path, section=section)


def merge_args(
    base: DataIo2026Args,
    overrides: DataIo2026ArgsTD | None = None,
) -> DataIo2026Args:
    return merge_model_data(base, overrides)


def dump_args(
    args: DataIo2026Args,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: DataIo2026Args, **_: Any) -> DataIo2026Args:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "DataIo2026Args",
    "DataIo2026ArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
