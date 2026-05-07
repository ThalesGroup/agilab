"""Application surface for the TeSciA diagnostic demo."""

from .app_args import (
    TesciaDiagnosticArgs,
    TesciaDiagnosticArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .diagnostic import (
    diagnose_case,
    evidence_quality,
    rank_candidate_fixes,
    regression_coverage,
    summarize_report,
)
from .reduction import (
    REDUCE_ARTIFACT_FILENAME_TEMPLATE,
    REDUCE_ARTIFACT_NAME,
    REDUCER_NAME,
    TESCIA_DIAGNOSTIC_REDUCE_CONTRACT,
    build_reduce_artifact,
    partial_from_diagnostic_summary,
    reduce_artifact_path,
    write_reduce_artifact,
)
from .tescia_diagnostic import TesciaDiagnostic, TesciaDiagnosticApp

__all__ = [
    "REDUCE_ARTIFACT_FILENAME_TEMPLATE",
    "REDUCE_ARTIFACT_NAME",
    "REDUCER_NAME",
    "TESCIA_DIAGNOSTIC_REDUCE_CONTRACT",
    "TesciaDiagnostic",
    "TesciaDiagnosticApp",
    "TesciaDiagnosticArgs",
    "TesciaDiagnosticArgsTD",
    "build_reduce_artifact",
    "diagnose_case",
    "dump_args",
    "ensure_defaults",
    "evidence_quality",
    "load_args",
    "merge_args",
    "partial_from_diagnostic_summary",
    "rank_candidate_fixes",
    "reduce_artifact_path",
    "regression_coverage",
    "summarize_report",
    "write_reduce_artifact",
]
