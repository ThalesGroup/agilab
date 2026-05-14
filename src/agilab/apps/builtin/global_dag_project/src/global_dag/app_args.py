"""Argument helpers for the built-in global DAG project."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class GlobalDagArgs(BaseModel):
    """Runtime parameters for the global DAG preview project."""

    model_config = ConfigDict(extra="forbid")

    dag_path: Path = Field(default_factory=lambda: Path("dag_templates/flight_to_weather_global_dag.json"))
    output_path: Path = Field(default_factory=lambda: Path("~/log/execute/global_dag/runner_state.json"))
    reset_target: bool = False


class GlobalDagArgsTD(TypedDict, total=False):
    dag_path: str
    output_path: str
    reset_target: bool


ArgsModel = GlobalDagArgs
ArgsOverrides = GlobalDagArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> GlobalDagArgs:
    return load_model_from_toml(GlobalDagArgs, settings_path, section=section)


def merge_args(base: GlobalDagArgs, overrides: GlobalDagArgsTD | None = None) -> GlobalDagArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: GlobalDagArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: GlobalDagArgs, **_: Any) -> GlobalDagArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "GlobalDagArgs",
    "GlobalDagArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
