"""Compatibility shim for ``agi_gui.widget_registry``.

The implementation now lives in ``agi_gui.widgets.widget_registry``. Keep this shim so
existing imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from agi_gui.compat.module_alias import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agi_gui.widgets.widget_registry"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
