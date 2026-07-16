"""Compatibility shim for AGI lifecycle guard helpers."""

from __future__ import annotations

from agi_cluster.agi_distributor.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agi_cluster.agi_distributor.runtime.lifecycle_guard_support"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
