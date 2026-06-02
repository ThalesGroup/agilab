"""Compatibility shim for ``agi_env.source_analysis_ast``.

The implementation now lives in ``agi_env.source.source_analysis_ast``. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from agi_env.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agi_env.source.source_analysis_ast"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
