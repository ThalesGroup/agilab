"""R stage smoke AGILAB app."""

from __future__ import annotations

from .app_args import (
    ArgsModel,
    ArgsOverrides,
    RStageSmokeArgs,
    RStageSmokeArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .r_stage_adapter import (
    RStageExecutionError,
    RStageResult,
    SCHEMA,
    build_r_stage_smoke_artifacts,
    run_r_stage,
)
from .r_stage_smoke import RStageSmoke, RStageSmokeApp
from .reduction import R_STAGE_SMOKE_REDUCE_CONTRACT

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "RStageExecutionError",
    "RStageResult",
    "RStageSmoke",
    "RStageSmokeApp",
    "RStageSmokeArgs",
    "RStageSmokeArgsTD",
    "R_STAGE_SMOKE_REDUCE_CONTRACT",
    "SCHEMA",
    "build_r_stage_smoke_artifacts",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
    "run_r_stage",
]
