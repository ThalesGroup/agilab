"""Argument management for Fireducks app template."""

from __future__ import annotations
from pathlib import Path
from typing import Any, TypedDict
from pydantic import BaseModel, ConfigDict, Field
from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data

class FireducksAppArgs(BaseModel):
    ...

class FireducksAppArgsTD(TypedDict):
    ...

ArgsModel = FireducksAppArgs

ArgsOverrides = FireducksAppArgsTD

def load_args(*args: Any, **kwargs: Any) -> Any: ...

def merge_args(*args: Any, **kwargs: Any) -> Any: ...

def dump_args(*args: Any, **kwargs: Any) -> Any: ...

def ensure_defaults(*args: Any, **kwargs: Any) -> Any: ...

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
