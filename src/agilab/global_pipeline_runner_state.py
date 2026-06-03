"""Compatibility shim for ``agilab.global_pipeline_runner_state``.

The implementation now lives in ``agilab.global_pipeline.global_pipeline_runner_state``. Keep this shim so existing
imports continue to work while internal code migrates to the classified
package layout.
"""

from __future__ import annotations

from agilab.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agilab.global_pipeline.global_pipeline_runner_state"
_module = _activate_compat_module(__name__, _TARGET_MODULE, legacy_name="agilab.global_pipeline_runner_state")
if _module is not None:
    globals().update(_module.__dict__)
