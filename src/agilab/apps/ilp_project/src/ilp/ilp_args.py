"""Argument definitions and helpers for the ILP project."""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from pydantic import BaseModel, Field, PositiveInt

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class IlpArgs(BaseModel):
    topology: str = Field(default="topo3N", description="Topology identifier understood by Flyenv")
    num_demands: PositiveInt = Field(default=3, description="Number of synthetic demands to generate")
    seed: int = Field(default=42, description="Random seed used for reproducible simulations")
    demand_scale: float = Field(default=1.0, ge=0.1, description="Scaling factor applied to generated bandwidths")
    data_uri: Path = Field(default_factory=lambda: Path("data/ilp"), description="Working directory for generated artefacts")


class IlpArgsTD(TypedDict, total=False):
    topology: str
    num_demands: int
    seed: int
    demand_scale: float
    data_uri: str


ArgsModel = IlpArgs
ArgsOverrides = IlpArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> IlpArgs:
    return load_model_from_toml(IlpArgs, settings_path, section=section)


def merge_args(base: IlpArgs, overrides: IlpArgsTD | None = None) -> IlpArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: IlpArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: IlpArgs, **_: object) -> IlpArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "IlpArgs",
    "IlpArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
