"""R runtime bridge AGILAB app."""

from __future__ import annotations

from .app_args import (
    ArgsModel,
    ArgsOverrides,
    RRuntimeBridgeArgs,
    RRuntimeBridgeArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .r_runtime_adapter import (
    RStageExecutionError,
    RStageResult,
    SCHEMA,
    build_r_runtime_bridge_artifacts,
    run_r_stage,
)
from .r_runtime_bridge import RRuntimeBridge, RRuntimeBridgeApp
from .reduction import R_RUNTIME_BRIDGE_REDUCE_CONTRACT

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "RStageExecutionError",
    "RStageResult",
    "RRuntimeBridge",
    "RRuntimeBridgeApp",
    "RRuntimeBridgeArgs",
    "RRuntimeBridgeArgsTD",
    "R_RUNTIME_BRIDGE_REDUCE_CONTRACT",
    "SCHEMA",
    "build_r_runtime_bridge_artifacts",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
    "run_r_stage",
]
