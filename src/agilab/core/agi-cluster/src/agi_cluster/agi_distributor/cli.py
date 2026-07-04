"""Compatibility shim for ``agi_cluster.agi_distributor.cli``.

The classified layout target is ``agi_cluster.agi_distributor.runtime.cli``. The
runtime behavior still delegates to ``agi_node.agi_dispatcher.cli`` so existing
cluster CLI imports and monkeypatch seams continue to work while internal code
migrates to the classified package layout.
"""

from __future__ import annotations

from agi_cluster.agi_distributor.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agi_cluster.agi_distributor.runtime.cli"
_WORKER_CLI_TARGET_MODULE = "agi_node.agi_dispatcher.cli"
_module = _activate_compat_module(__name__, _WORKER_CLI_TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
