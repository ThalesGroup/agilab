"""Compatibility shim for ``agilab.secret_uri``.

The implementation now lives in ``agilab.security.secret_uri``. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from agilab.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agilab.security.secret_uri"
_module = _activate_compat_module(__name__, _TARGET_MODULE, legacy_name="agilab.secret_uri")
if _module is not None:
    globals().update(_module.__dict__)
