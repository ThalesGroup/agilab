"""Compatibility loaders for UI helpers that are moving out of agi-env."""

from __future__ import annotations

from importlib import import_module
import sys
from types import ModuleType


def activate_compat_module(current_name: str, target_name: str) -> ModuleType:
    """Expose ``target_name`` under ``current_name`` for legacy imports."""

    module = import_module(target_name)
    sys.modules[current_name] = module
    return module


def alias_agi_env_module(target_name: str, source_name: str) -> ModuleType:
    """Expose an existing agi_env UI module under the agi_gui namespace."""

    module = import_module(source_name)
    sys.modules[target_name] = module
    return module
