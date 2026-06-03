"""Argument management for the simple app template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class SimpleAppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_out: Path = Field(default_factory=lambda: Path("simple_app/artifacts"))
    title: str = "Simple AGILAB app"
    note: str = "Replace this note with the app-specific local workflow."


class SimpleAppArgsTD(TypedDict, total=False):
    data_out: str
    title: str
    note: str


ArgsModel = SimpleAppArgs
ArgsOverrides = SimpleAppArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> SimpleAppArgs:
    return load_model_from_toml(SimpleAppArgs, settings_path, section=section)


def merge_args(
    base: SimpleAppArgs,
    overrides: SimpleAppArgsTD | None = None,
) -> SimpleAppArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: SimpleAppArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: SimpleAppArgs, **_: Any) -> SimpleAppArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "SimpleAppArgs",
    "SimpleAppArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
