"""Argument management for the DAG app template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class DagAppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_uri: Path = Field(default_factory=lambda: Path("~/data/DagApp"))


class DagAppArgsTD(TypedDict, total=False):
    data_uri: str


ArgsModel = DagAppArgs
ArgsOverrides = DagAppArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> DagAppArgs:
    return load_model_from_toml(DagAppArgs, settings_path, section=section)


def merge_args(base: DagAppArgs, overrides: DagAppArgsTD | None = None) -> DagAppArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: DagAppArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: DagAppArgs, **_: Any) -> DagAppArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "DagAppArgs",
    "DagAppArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]

