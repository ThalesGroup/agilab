"""Argument helpers for the built-in multi-app DAG project."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class MultiAppDagArgs(BaseModel):
    """Runtime parameters for the multi-app DAG preview project."""

    model_config = ConfigDict(extra="forbid")

    dag_path: Path = Field(default_factory=lambda: Path("dag_templates/flight_to_weather_legacy_multi_app_dag.json"))
    output_path: Path = Field(default_factory=lambda: Path("~/log/execute/multi_app_dag/runner_state.json"))
    reset_target: bool = False


class MultiAppDagArgsTD(TypedDict, total=False):
    dag_path: str
    output_path: str
    reset_target: bool


ArgsModel = MultiAppDagArgs
ArgsOverrides = MultiAppDagArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> MultiAppDagArgs:
    return load_model_from_toml(MultiAppDagArgs, settings_path, section=section)


def merge_args(base: MultiAppDagArgs, overrides: MultiAppDagArgsTD | None = None) -> MultiAppDagArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: MultiAppDagArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: MultiAppDagArgs, **_: Any) -> MultiAppDagArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "MultiAppDagArgs",
    "MultiAppDagArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
