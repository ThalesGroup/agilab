"""Shared validation and persistence helpers for Flight project arguments."""

from __future__ import annotations
import re
import socket
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypedDict
import tomli
from pydantic import BaseModel, ConfigDict, Field, field_validator
from agi_env.app_args import (
    dump_model_to_toml,
    load_model_from_toml,
    merge_model_data,
    model_to_payload,
)

ARGS_SECTION = "args"

_DATEMIN_LOWER_BOUND = date(2020, 1, 1)

_DATEMAX_UPPER_BOUND = date(2021, 6, 1)

class FlightArgs(BaseModel):
    def _coerce_data_uri(cls, *args: Any, **kwargs: Any) -> Any: ...
    def _check_datemin(cls, *args: Any, **kwargs: Any) -> Any: ...
    def _check_datemax(cls, *args: Any, **kwargs: Any) -> Any: ...
    def _check_regex(cls, *args: Any, **kwargs: Any) -> Any: ...
    def to_toml_payload(self) -> Any: ...

class FlightArgsTD(TypedDict):
    ...

def load_args_from_toml(*args: Any, **kwargs: Any) -> Any: ...

def merge_args(*args: Any, **kwargs: Any) -> Any: ...

def apply_source_defaults(*args: Any, **kwargs: Any) -> Any: ...

def dump_args_to_toml(*args: Any, **kwargs: Any) -> Any: ...

ArgsModel = FlightArgs

ArgsOverrides = FlightArgsTD

def load_args(*args: Any, **kwargs: Any) -> Any: ...

def dump_args(*args: Any, **kwargs: Any) -> Any: ...

def ensure_defaults(*args: Any, **kwargs: Any) -> Any: ...

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "FlightArgs",
    "FlightArgsTD",
    "apply_source_defaults",
    "dump_args",
    "dump_args_to_toml",
    "ensure_defaults",
    "load_args",
    "load_args_from_toml",
    "merge_args",
]
