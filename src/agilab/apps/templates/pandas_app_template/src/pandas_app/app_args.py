"""Argument management for Pandas app template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class PandasAppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_uri: Path = Field(default_factory=lambda: Path("~/data/PandasApp"))


class PandasAppArgsTD(TypedDict, total=False):
    data_uri: str


ArgsModel = PandasAppArgs
ArgsOverrides = PandasAppArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> PandasAppArgs:
    return load_model_from_toml(PandasAppArgs, settings_path, section=section)


def merge_args(
    base: PandasAppArgs,
    overrides: PandasAppArgsTD | None = None,
) -> PandasAppArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: PandasAppArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: PandasAppArgs, **_: Any) -> PandasAppArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "PandasAppArgs",
    "PandasAppArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]

