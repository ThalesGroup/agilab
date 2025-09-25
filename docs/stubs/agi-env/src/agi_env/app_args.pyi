"""Utilities for loading and persisting app argument models."""

from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Type, TypeVar
import tomllib
from pydantic import BaseModel, ValidationError

TModel = TypeVar("TModel", bound=BaseModel)

def model_to_payload(*args: Any, **kwargs: Any) -> Any: ...

def merge_model_data(*args: Any, **kwargs: Any) -> Any: ...

def load_model_from_toml(*args: Any, **kwargs: Any) -> Any: ...

def dump_model_to_toml(*args: Any, **kwargs: Any) -> Any: ...
