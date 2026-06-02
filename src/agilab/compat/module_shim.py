"""Runtime helper for backwards-compatible AGILAB module shims."""

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
            "_AGILAB_COMPAT_TARGET_MODULE",
        }:
            return ModuleType.__getattribute__(self, name)
        target = ModuleType.__getattribute__(self, "__dict__").get(
            "_AGILAB_COMPAT_TARGET_MODULE"
        )
        if target is not None and hasattr(target, name):
            return getattr(target, name)
        return ModuleType.__getattribute__(self, name)

    def __setattr__(self, name: str, value):
        ModuleType.__setattr__(self, name, value)
        target = self.__dict__.get("_AGILAB_COMPAT_TARGET_MODULE")
        if target is not None and name not in {
            "__class__",
            "_AGILAB_COMPAT_TARGET_MODULE",
        }:
            setattr(target, name, value)

    def __delattr__(self, name: str):
        target = self.__dict__.get("_AGILAB_COMPAT_TARGET_MODULE")
        ModuleType.__delattr__(self, name)
        if target is not None and hasattr(target, name):
            delattr(target, name)


def _execute_target_in_current_module(
    current_name: str, target_name: str, namespace: dict[str, object] | None = None
) -> ModuleType | None:
    current_module = sys.modules.get(current_name)
    spec = importlib.util.find_spec(target_name)
    target_namespace = current_module.__dict__ if current_module is not None else namespace
    if target_namespace is None or spec is None or spec.origin is None:
        return importlib.import_module(target_name)
    target_package = target_name.rpartition(".")[0]
    target_namespace["__file__"] = spec.origin
    target_namespace["__package__"] = target_package
    source = compile(
        open(spec.origin, encoding="utf-8").read(),
        spec.origin,
        "exec",
    )
    exec(source, target_namespace)
    return None


def activate_compat_module(
    current_name: str, target_name: str, *, legacy_name: str | None = None
) -> ModuleType | None:
    """Expose ``target_name`` through the legacy ``current_name`` module path.

    The helper keeps ``import agilab.<legacy>`` working after moving the real
    module into a classified subpackage. When a shim is executed as a module,
    it delegates to the target module with ``__main__`` semantics.
    """

    if current_name == "__main__":
        runpy.run_module(target_name, run_name="__main__")
        return None

    if (
        legacy_name is not None
        and (current_name != legacy_name or not current_name.startswith("agilab."))
    ):
        caller_globals = sys._getframe(1).f_globals
        return _execute_target_in_current_module(
            current_name, target_name, namespace=caller_globals
        )

    module = importlib.import_module(target_name)
    current_module = sys.modules.get(current_name)
    if current_module is None:
        return module
    current_module.__dict__.update(module.__dict__)
    current_module.__dict__["_AGILAB_COMPAT_TARGET_MODULE"] = module
    current_module.__class__ = _CompatModule
    return None
