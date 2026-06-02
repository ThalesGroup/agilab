"""Compatibility shim for ``agilab.ci_provider_artifacts``.

The implementation now lives in ``agilab.ci.ci_provider_artifacts``. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from agilab.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agilab.ci.ci_provider_artifacts"
_module = _activate_compat_module(__name__, _TARGET_MODULE, legacy_name="agilab.ci_provider_artifacts")
if _module is not None:
    globals().update(_module.__dict__)
