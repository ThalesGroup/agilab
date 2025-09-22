"""Argument definitions and helpers for Mycode project."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class MycodeArgs(BaseModel):
    param1: int = Field(default=0)
    param2: str = Field(default="some text")
    param3: float = Field(default=3.14)
    param4: bool = Field(default=True)


class MycodeArgsTD(TypedDict, total=False):
    param1: int
    param2: str
    param3: float
    param4: bool


ArgsModel = MycodeArgs
ArgsOverrides = MycodeArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> MycodeArgs:
    return load_model_from_toml(MycodeArgs, settings_path, section=section)


def merge_args(base: MycodeArgs, overrides: MycodeArgsTD | None = None) -> MycodeArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: MycodeArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: MycodeArgs, **_: Any) -> MycodeArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "MycodeArgs",
    "MycodeArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
