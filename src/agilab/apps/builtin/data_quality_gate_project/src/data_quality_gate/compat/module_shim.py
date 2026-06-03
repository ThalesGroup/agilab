"""Compatibility loader for classified data quality gate package modules."""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_CLASSIFICATION_SEGMENTS = {"domain", "runtime"}


class _CompatModule(ModuleType):
    """Forward monkeypatches on legacy modules to their classified targets."""

    _target_module: ModuleType
    _compat_target_name: str

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if name.startswith("_"):
            return
        target = self.__dict__.get("_target_module")
        if target is not None:
            setattr(target, name, value)


class _CompatModuleLoader(importlib.abc.Loader):
    def __init__(self, target_name: str) -> None:
        self._target_name = target_name

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        return _compat_module_from_target(spec.name, self._target_name)

    def exec_module(self, module: ModuleType) -> None:
        return None


def _legacy_name_for_target(target_name: str) -> str:
    parts = target_name.split(".")
    for index, part in enumerate(parts):
        if part in _CLASSIFICATION_SEGMENTS:
            return ".".join(parts[:index] + parts[index + 1 :])
    return target_name


def _module_from_target(target_name: str, target: ModuleType) -> _CompatModule:
    legacy_name = _legacy_name_for_target(target_name)
    module = _CompatModule(legacy_name, target.__doc__)
    module.__dict__.update(target.__dict__)
    module.__name__ = legacy_name
    module.__package__ = legacy_name.rpartition(".")[0]
    module.__loader__ = _CompatModuleLoader(target_name)
    module.__spec__ = importlib.machinery.ModuleSpec(legacy_name, module.__loader__)
    module.__file__ = getattr(target, "__file__", None)
    module.__dict__["_target_module"] = target
    module.__dict__["_compat_target_name"] = target_name
    module.__dict__["_TARGET_MODULE"] = target_name
    return module


def _compat_module_from_target(legacy_name: str, target_name: str) -> _CompatModule:
    target = importlib.import_module(target_name)
    module = _module_from_target(target_name, target)
    module.__name__ = legacy_name
    module.__package__ = legacy_name.rpartition(".")[0]
    if module.__spec__ is not None:
        module.__spec__.name = legacy_name
    sys.modules[legacy_name] = module
    return module


def _execute_target_in_current_module(current_name: str, target_name: str) -> None:
    target_spec = importlib.util.find_spec(target_name)
    if target_spec is None or target_spec.origin is None:
        raise ImportError(f"Cannot resolve classified data quality gate module {target_name!r}")
    current = sys.modules[current_name]
    current.__file__ = target_spec.origin
    current.__package__ = target_name.rpartition(".")[0]
    current.__loader__ = target_spec.loader
    current.__spec__ = target_spec
    current.__dict__["_TARGET_MODULE"] = target_name
    source = Path(target_spec.origin).read_text(encoding="utf-8")
    code = compile(source, target_spec.origin, "exec")
    exec(code, current.__dict__)


def activate_compat_module(current_name: str, target_name: str) -> None:
    """Expose a classified target under its legacy package-layout module name."""

    legacy_name = _legacy_name_for_target(target_name)
    if current_name != legacy_name:
        _execute_target_in_current_module(current_name, target_name)
        return
    _compat_module_from_target(current_name, target_name)
