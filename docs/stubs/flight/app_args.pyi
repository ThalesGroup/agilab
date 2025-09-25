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

def ensure_defaults(*args: Any, **kwargs: Any) -> Any: ...

def load_args(*args: Any, **kwargs: Any) -> Any: ...

def dump_args(*args: Any, **kwargs: Any) -> Any: ...

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
