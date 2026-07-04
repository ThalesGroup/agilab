"""Data quality gate AGILAB app."""

from __future__ import annotations

from .runtime.app_args import (
    ArgsModel,
    ArgsOverrides,
    DataQualityGateArgs,
    DataQualityGateArgsTD,
    dump_args,
    ensure_defaults,
    filter_arg_overrides,
    load_args,
    merge_args,
    safe_reset_path,
    share_root_from_env,
    validate_relative_data_out,
)
from .domain.core import (
    CONTRACT_COLUMNS,
    CONTRACT_SCHEMA,
    SCHEMA,
    THRESHOLDS,
    THRESHOLDS_SCHEMA,
    build_data_quality_gate_artifacts,
    default_contract,
)
from .runtime.data_quality_gate import DataQualityGate, DataQualityGateApp
from .reduction import (
    DATA_QUALITY_GATE_REDUCE_CONTRACT,
    REDUCE_ARTIFACT_FILENAME_TEMPLATE,
    REDUCE_ARTIFACT_NAME,
    REDUCER_NAME,
    build_reduce_artifact,
    partial_from_gate_summary,
    reduce_artifact_path,
    write_reduce_artifact,
)

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "CONTRACT_COLUMNS",
    "CONTRACT_SCHEMA",
    "DATA_QUALITY_GATE_REDUCE_CONTRACT",
    "DataQualityGate",
    "DataQualityGateApp",
    "DataQualityGateArgs",
    "DataQualityGateArgsTD",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "SCHEMA",
    "THRESHOLDS",
    "THRESHOLDS_SCHEMA",
    "build_data_quality_gate_artifacts",
    "build_reduce_artifact",
    "default_contract",
    "dump_args",
    "ensure_defaults",
    "filter_arg_overrides",
    "load_args",
    "merge_args",
    "partial_from_gate_summary",
    "reduce_artifact_path",
    "safe_reset_path",
    "share_root_from_env",
    "validate_relative_data_out",
    "write_reduce_artifact",
]
