"""Compatibility helpers exposing Flight argument utilities under a common API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .flight_args import (
    FlightArgs,
    FlightArgsTD,
    apply_source_defaults,
    dump_args_to_toml,
    load_args_from_toml,
    merge_args,
)

ArgsModel = FlightArgs
ArgsOverrides = FlightArgsTD


def ensure_defaults(args: FlightArgs, **kwargs: Any) -> FlightArgs:
    return apply_source_defaults(args, **kwargs)


def load_args(settings_path: str | Path, section: str = "args") -> FlightArgs:
    return load_args_from_toml(settings_path, section=section)


def dump_args(
    args: FlightArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_args_to_toml(args, settings_path, section=section, create_missing=create_missing)


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "ensure_defaults",
    "load_args",
    "dump_args",
    "merge_args",
    "FlightArgs",
    "FlightArgsTD",
]

