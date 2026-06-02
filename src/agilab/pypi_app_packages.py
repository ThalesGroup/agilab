"""Compatibility shim for ``agilab.pypi_app_packages``.

The implementation now lives in ``agilab.app_management.pypi_app_packages``. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from agilab.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agilab.app_management.pypi_app_packages"
_module = _activate_compat_module(__name__, _TARGET_MODULE, legacy_name="agilab.pypi_app_packages")
if _module is not None:
    globals().update(_module.__dict__)
