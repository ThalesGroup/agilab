"""Argument management for the Agent app template."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class AgentAppArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_dir: Path = Field(default_factory=lambda: Path("~/data/AgentApp"))


class AgentAppArgsTD(TypedDict, total=False):
    data_dir: str


ArgsModel = AgentAppArgs
ArgsOverrides = AgentAppArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> AgentAppArgs:
    return load_model_from_toml(AgentAppArgs, settings_path, section=section)


def merge_args(base: AgentAppArgs, overrides: AgentAppArgsTD | None = None) -> AgentAppArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: AgentAppArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: AgentAppArgs, **_: Any) -> AgentAppArgs:
    return args


__all__ = [
    "AgentAppArgs",
    "AgentAppArgsTD",
    "ArgsModel",
    "ArgsOverrides",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]

