"""Compatibility shim for the classified data quality gate reducer package layout."""

from __future__ import annotations

from data_quality_gate.compat.module_shim import activate_compat_module

_TARGET_MODULE = "data_quality_gate.runtime.reduction"

# Public reducer contract markers kept here for static adoption guards:
# REDUCE_ARTIFACT_FILENAME_TEMPLATE = "reduce_summary_worker_{worker_id}.json"
# write_reduce_artifact is exposed by the classified target module.

activate_compat_module(__name__, _TARGET_MODULE)
