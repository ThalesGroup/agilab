"""Argument management for Fireducks app template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class FireducksAppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_keys(cls, data: Any):
        if isinstance(data, dict) and "data_uri" in data and "data_in" not in data:
            data = dict(data)
            data["data_in"] = data.pop("data_uri")
        return data

    data_in: Path = Field(default_factory=lambda: Path("data/FireducksApp"))


class FireducksAppArgsTD(TypedDict, total=False):
    data_in: str


ArgsModel = FireducksAppArgs
ArgsOverrides = FireducksAppArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> FireducksAppArgs:
    return load_model_from_toml(FireducksAppArgs, settings_path, section=section)


def merge_args(
    base: FireducksAppArgs,
    overrides: FireducksAppArgsTD | None = None,
) -> FireducksAppArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: FireducksAppArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: FireducksAppArgs, **_: Any) -> FireducksAppArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "FireducksAppArgs",
    "FireducksAppArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
