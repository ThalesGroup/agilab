"""Scikit-learn pipeline AGILAB app."""

from __future__ import annotations

from .app_args import (
    ArgsModel,
    ArgsOverrides,
    SklearnPipelineArgs,
    SklearnPipelineArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .core import SCHEMA, build_sklearn_pipeline_artifacts
from .reduction import SKLEARN_PIPELINE_REDUCE_CONTRACT
from .sklearn_pipeline import SklearnPipeline, SklearnPipelineApp

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "SCHEMA",
    "SklearnPipeline",
    "SklearnPipelineApp",
    "SklearnPipelineArgs",
    "SklearnPipelineArgsTD",
    "SKLEARN_PIPELINE_REDUCE_CONTRACT",
    "build_sklearn_pipeline_artifacts",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
