"""Compatibility shim for ``pytorch_playground.app_args``.

The implementation now lives in ``pytorch_playground.runtime.app_args``. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from pytorch_playground.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "pytorch_playground.runtime.app_args"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
