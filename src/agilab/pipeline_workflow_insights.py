"""Compatibility shim for ``agilab.pipeline_workflow_insights``."""

from __future__ import annotations

from agilab.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "agilab.pipeline.pipeline_workflow_insights"
_module = _activate_compat_module(__name__, _TARGET_MODULE, legacy_name="agilab.pipeline_workflow_insights")
if _module is not None:
    globals().update(_module.__dict__)
