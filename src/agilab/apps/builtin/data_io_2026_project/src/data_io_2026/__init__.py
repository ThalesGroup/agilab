"""Application surface for the public Data IO 2026 demo."""

from .app_args import (
    DataIo2026Args,
    DataIo2026ArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .artifacts import (
    MissionWeights,
    apply_failure_events,
    build_decision_artifacts,
    build_generated_pipeline,
    choose_route,
    score_routes,
)
from .data_io_2026 import DataIo2026, DataIo2026App
from .reduction import (
    DATA_IO_2026_REDUCE_CONTRACT,
    REDUCE_ARTIFACT_FILENAME_TEMPLATE,
    REDUCE_ARTIFACT_NAME,
    REDUCER_NAME,
    build_reduce_artifact,
    partial_from_decision_summary,
    reduce_artifact_path,
    write_reduce_artifact,
)

__all__ = [
    "DATA_IO_2026_REDUCE_CONTRACT",
    "DataIo2026",
    "DataIo2026App",
    "DataIo2026Args",
    "DataIo2026ArgsTD",
    "MissionWeights",
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "apply_failure_events",
    "build_reduce_artifact",
    "build_decision_artifacts",
    "build_generated_pipeline",
    "choose_route",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
    "partial_from_decision_summary",
    "reduce_artifact_path",
    "score_routes",
    "write_reduce_artifact",
]
