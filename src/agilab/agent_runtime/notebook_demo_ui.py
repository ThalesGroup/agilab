"""Compatibility alias for :mod:`agilab.demos.notebook_demo_ui`."""

from __future__ import annotations

from agilab.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agilab.demos.notebook_demo_ui"
_module = _activate_compat_module(
    __name__, _TARGET_MODULE, legacy_name="agilab.agent_runtime.notebook_demo_ui"
)
if _module is not None:
    globals().update(_module.__dict__)
