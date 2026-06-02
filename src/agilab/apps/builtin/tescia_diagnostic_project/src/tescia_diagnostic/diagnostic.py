"""Compatibility shim for tescia_diagnostic.diagnostic.

The implementation now lives in tescia_diagnostic.domain.diagnostic. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from tescia_diagnostic.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "tescia_diagnostic.domain.diagnostic"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
