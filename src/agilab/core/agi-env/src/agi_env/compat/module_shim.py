"""Runtime helper for backwards-compatible module shims."""

from __future__ import annotations

import importlib
import importlib.util
import runpy
import sys
from types import ModuleType


class _CompatModule(ModuleType):
    """Module proxy that forwards monkeypatches to the classified target."""

    def __getattribute__(self, name: str):
        if name in {
            "__class__",
            "__dict__",
            "__doc__",
            "__file__",
            "__loader__",
            "__name__",
            "__package__",
            "__spec__",
            "_COMPAT_TARGET_MODULE",
        }:
            return ModuleType.__getattribute__(self, name)
        target = ModuleType.__getattribute__(self, "__dict__").get("_COMPAT_TARGET_MODULE")
        if target is not None and hasattr(target, name):
            return getattr(target, name)
        return ModuleType.__getattribute__(self, name)

    def __setattr__(self, name: str, value):
        ModuleType.__setattr__(self, name, value)
        target = self.__dict__.get("_COMPAT_TARGET_MODULE")
        if target is not None and name not in {"__class__", "_COMPAT_TARGET_MODULE"}:
            setattr(target, name, value)

    def __delattr__(self, name: str):
        target = self.__dict__.get("_COMPAT_TARGET_MODULE")
        ModuleType.__delattr__(self, name)
        if target is not None and hasattr(target, name):
            delattr(target, name)


def _legacy_name_for_target(target_name: str) -> str:
    parts = target_name.split(".")
    if parts[:1] == ["agi_env"] and len(parts) >= 3:
        return ".".join(parts[:1] + parts[2:])
    return target_name


def _execute_target_in_current_module(current_name: str, target_name: str) -> ModuleType | None:
    current_module = sys.modules.get(current_name)
    spec = importlib.util.find_spec(target_name)
    if current_module is None or spec is None or spec.origin is None:
        return importlib.import_module(target_name)
    target_package = target_name.rpartition(".")[0]
    current_module.__dict__["__file__"] = spec.origin
    current_module.__dict__["__package__"] = target_package
    source = compile(
        open(spec.origin, encoding="utf-8").read(),
        spec.origin,
        "exec",
    )
    exec(source, current_module.__dict__)
    return None


def activate_compat_module(current_name: str, target_name: str) -> ModuleType | None:
    """Expose ``target_name`` through the legacy ``current_name`` module path."""

    if current_name == "__main__":
        runpy.run_module(target_name, run_name="__main__")
        return None

    if current_name != _legacy_name_for_target(target_name):
        return _execute_target_in_current_module(current_name, target_name)

    module = importlib.import_module(target_name)
    current_module = sys.modules.get(current_name)
    if current_module is None:
        return module
    current_module.__dict__.update(module.__dict__)
    current_module.__dict__["_COMPAT_TARGET_MODULE"] = module
    current_module.__class__ = _CompatModule
    return None
