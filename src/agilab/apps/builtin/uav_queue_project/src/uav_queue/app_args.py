"""Argument helpers for the built-in UAV relay queue example."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class UavQueueArgs(BaseModel):
    """Runtime parameters for the lightweight UAV relay queue demo."""

    model_config = ConfigDict(extra="forbid")

    data_in: Path = Field(default_factory=lambda: Path("uav_queue/scenarios"))
    data_out: Path = Field(default_factory=lambda: Path("uav_queue/results"))
    files: str = "*.json"
    nfile: int = Field(default=1, ge=1, le=50)
    routing_policy: Literal["shortest_path", "queue_aware"] = "shortest_path"
    sim_time_s: float = Field(default=30.0, gt=1.0, le=600.0)
    sampling_interval_s: float = Field(default=0.5, gt=0.0, le=10.0)
    source_rate_pps: float = Field(default=14.0, gt=0.0, le=500.0)
    queue_weight: float = Field(default=2.5, ge=0.0, le=20.0)
    random_seed: int = Field(default=2026, ge=0)
    reset_target: bool = False

    @model_validator(mode="after")
    def _validate_consistency(self) -> "UavQueueArgs":
        self.files = self.files.strip() or "*.json"
        if self.sampling_interval_s >= self.sim_time_s:
            raise ValueError("sampling_interval_s must be smaller than sim_time_s")
        return self


class UavQueueArgsTD(TypedDict, total=False):
    data_in: str
    data_out: str
    files: str
    nfile: int
    routing_policy: str
    sim_time_s: float
    sampling_interval_s: float
    source_rate_pps: float
    queue_weight: float
    random_seed: int
    reset_target: bool


ArgsModel = UavQueueArgs
ArgsOverrides = UavQueueArgsTD
UavRelayQueueArgs = UavQueueArgs
UavRelayQueueArgsTD = UavQueueArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> UavQueueArgs:
    return load_model_from_toml(UavQueueArgs, settings_path, section=section)


def merge_args(base: UavQueueArgs, overrides: UavQueueArgsTD | None = None) -> UavQueueArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: UavQueueArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: UavQueueArgs, **_: Any) -> UavQueueArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "UavRelayQueueArgs",
    "UavRelayQueueArgsTD",
    "UavQueueArgs",
    "UavQueueArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
