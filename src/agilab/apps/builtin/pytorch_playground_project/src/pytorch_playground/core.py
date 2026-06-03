"""Compatibility shim for ``pytorch_playground.core``.

The implementation now lives in ``pytorch_playground.domain.core``. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from pytorch_playground.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "pytorch_playground.domain.core"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
