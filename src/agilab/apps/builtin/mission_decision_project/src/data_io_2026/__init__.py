"""Application surface for the public Mission Decision demo."""

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
from .fred_support import (
    FRED_CSV_BASE_URL,
    FRED_FIXTURE_CSV,
    FRED_FIXTURE_SERIES_ID,
    FRED_FIXTURE_SERIES_NAME,
    fetch_fred_csv_rows,
    fred_csv_url,
    fred_fixture_feature_rows,
    fred_fixture_rows,
    parse_fred_csv,
)
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
    "FRED_CSV_BASE_URL",
    "FRED_FIXTURE_CSV",
    "FRED_FIXTURE_SERIES_ID",
    "FRED_FIXTURE_SERIES_NAME",
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
    "fetch_fred_csv_rows",
    "fred_csv_url",
    "fred_fixture_feature_rows",
    "fred_fixture_rows",
    "load_args",
    "merge_args",
    "partial_from_decision_summary",
    "parse_fred_csv",
    "reduce_artifact_path",
    "score_routes",
    "write_reduce_artifact",
]
