"""Compatibility shim for learning_assessment.learning_assessment.

The implementation now lives in learning_assessment.runtime.learning_assessment. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from learning_assessment.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "learning_assessment.runtime.learning_assessment"
_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
