"""Argument management helpers for the mycode sample project."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class MycodeArgs(BaseModel):
    """Runtime parameters for the mycode application."""

    model_config = ConfigDict(extra="forbid")

    data_uri: Path = Field(default_factory=lambda: Path("~/data/mycode"))
    files: str = "*"
    nfile: int = 1
    nskip: int = 0
    nread: int = 0


class MycodeArgsTD(TypedDict, total=False):
    data_uri: str
    files: str
    nfile: int
    nskip: int
    nread: int


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
