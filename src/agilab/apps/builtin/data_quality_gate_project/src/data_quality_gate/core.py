"""Compatibility shim for the classified data quality gate package layout."""

from __future__ import annotations

from data_quality_gate.compat.module_shim import activate_compat_module

_TARGET_MODULE = "data_quality_gate.domain.core"

activate_compat_module(__name__, _TARGET_MODULE)
