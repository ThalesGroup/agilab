"""Compatibility shim for the classified PyTorch playground reducer package layout."""

from __future__ import annotations

from pytorch_playground.compat.module_shim import activate_compat_module as _activate_compat_module

_TARGET_MODULE = "pytorch_playground.runtime.reduction"

# Public reducer contract markers kept here for static adoption guards:
# REDUCE_ARTIFACT_FILENAME_TEMPLATE = "reduce_summary_worker_{worker_id}.json"
# write_reduce_artifact is exposed by the classified target module.

_module = _activate_compat_module(__name__, _TARGET_MODULE)
if _module is not None:
    globals().update(_module.__dict__)
