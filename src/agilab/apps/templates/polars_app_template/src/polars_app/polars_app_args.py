"""Argument management for the Polars app template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class PolarsAppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_uri: Path = Field(default_factory=lambda: Path("~/data/PolarsApp"))


class PolarsAppArgsTD(TypedDict, total=False):
    data_uri: str


ArgsModel = PolarsAppArgs
ArgsOverrides = PolarsAppArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> PolarsAppArgs:
    return load_model_from_toml(PolarsAppArgs, settings_path, section=section)


def merge_args(base: PolarsAppArgs, overrides: PolarsAppArgsTD | None = None) -> PolarsAppArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: PolarsAppArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: PolarsAppArgs, **_: Any) -> PolarsAppArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "PolarsAppArgs",
    "PolarsAppArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]

