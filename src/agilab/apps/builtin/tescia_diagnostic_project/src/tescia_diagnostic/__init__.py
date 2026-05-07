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
    student_score,
    summarize_report,
)
from .generator import (
    DEFAULT_GPT_OSS_ENDPOINT,
    DEFAULT_GPT_OSS_MODEL,
    DEFAULT_OLLAMA_ENDPOINT,
    DEFAULT_OLLAMA_MODEL,
    DiagnosticCaseGenerationError,
    build_generation_prompt,
    generate_case_file,
    generate_cases_with_engine,
    validate_generated_cases,
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
    "DEFAULT_GPT_OSS_ENDPOINT",
    "DEFAULT_GPT_OSS_MODEL",
    "DEFAULT_OLLAMA_ENDPOINT",
    "DEFAULT_OLLAMA_MODEL",
    "DiagnosticCaseGenerationError",
    "TESCIA_DIAGNOSTIC_REDUCE_CONTRACT",
    "TesciaDiagnostic",
    "TesciaDiagnosticApp",
    "TesciaDiagnosticArgs",
    "TesciaDiagnosticArgsTD",
    "build_generation_prompt",
    "build_reduce_artifact",
    "diagnose_case",
    "dump_args",
    "ensure_defaults",
    "evidence_quality",
    "generate_case_file",
    "generate_cases_with_engine",
    "load_args",
    "merge_args",
    "partial_from_diagnostic_summary",
    "rank_candidate_fixes",
    "reduce_artifact_path",
    "regression_coverage",
    "student_score",
    "summarize_report",
    "validate_generated_cases",
    "write_reduce_artifact",
]
