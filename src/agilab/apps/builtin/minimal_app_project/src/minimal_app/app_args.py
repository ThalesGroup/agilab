"""Argument management helpers for the minimal_app sample project."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class MinimalAppArgs(BaseModel):
    """Runtime parameters for the minimal_app application."""

    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_keys(cls, data: Any):
        if isinstance(data, dict) and "data_uri" in data and "data_in" not in data:
            data = dict(data)
            data["data_in"] = data.pop("data_uri")
        return data

    data_in: Path = Field(default_factory=lambda: Path("minimal_app/dataset"))
    data_out: Path = Field(default_factory=lambda: Path("minimal_app/dataframe"))
    files: str = "*"
    nfile: int = 1
    nskip: int = 0
    nread: int = 0
    reset_target: bool = False


class MinimalAppArgsTD(TypedDict, total=False):
    data_in: str
    data_out: str
    files: str
    nfile: int
    nskip: int
    nread: int
    reset_target: bool


ArgsModel = MinimalAppArgs
ArgsOverrides = MinimalAppArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> MinimalAppArgs:
    return load_model_from_toml(MinimalAppArgs, settings_path, section=section)


def merge_args(base: MinimalAppArgs, overrides: MinimalAppArgsTD | None = None) -> MinimalAppArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: MinimalAppArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: MinimalAppArgs, **_: Any) -> MinimalAppArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "MinimalAppArgs",
    "MinimalAppArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]

