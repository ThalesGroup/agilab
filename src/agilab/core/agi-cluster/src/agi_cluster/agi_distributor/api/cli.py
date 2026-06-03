"""Compatibility shim for the node-owned worker CLI."""

from __future__ import annotations

from agi_cluster.agi_distributor.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agi_node.agi_dispatcher.cli"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
