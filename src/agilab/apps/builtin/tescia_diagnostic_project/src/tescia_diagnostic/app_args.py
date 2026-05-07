"""Argument helpers for the TeSciA diagnostic built-in app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data

from .generator import DEFAULT_GPT_OSS_ENDPOINT, DEFAULT_GPT_OSS_MODEL


class TesciaDiagnosticArgs(BaseModel):
    """Runtime parameters for the TeSciA diagnostic application."""

    model_config = ConfigDict(extra="forbid")

    data_in: Path = Field(default_factory=lambda: Path("tescia_diagnostic/cases"))
    data_out: Path = Field(default_factory=lambda: Path("tescia_diagnostic/reports"))
    files: str = "*.json"
    nfile: int = Field(default=1, ge=1, le=50)
    minimum_evidence_confidence: float = Field(default=0.65, ge=0.0, le=1.0)
    minimum_regression_coverage: float = Field(default=0.6, ge=0.0, le=1.0)
    reset_target: bool = False
    case_source: Literal["bundled", "standalone_ai"] = "bundled"
    generated_cases_filename: str = "tescia_diagnostic_cases.generated.json"
    regenerate_cases: bool = False
    ai_provider: Literal["gpt-oss", "ollama"] = "gpt-oss"
    ai_endpoint: str = DEFAULT_GPT_OSS_ENDPOINT
    ai_model: str = DEFAULT_GPT_OSS_MODEL
    ai_topic: str = "AGILAB engineering diagnostics, cluster runs, pipeline DAGs, and evidence-backed fixes"
    ai_case_count: int = Field(default=2, ge=1, le=5)
    ai_temperature: float = Field(default=0.2, ge=0.0, le=1.0)
    ai_timeout_s: float = Field(default=120.0, ge=1.0, le=600.0)

    @model_validator(mode="after")
    def _validate_file_glob(self) -> "TesciaDiagnosticArgs":
        self.files = self.files.strip() or "*.json"
        if not self.files.endswith(".json"):
            raise ValueError("files must select JSON diagnostic case files")
        self.generated_cases_filename = self.generated_cases_filename.strip()
        if (
            not self.generated_cases_filename
            or "/" in self.generated_cases_filename
            or "\\" in self.generated_cases_filename
            or not self.generated_cases_filename.endswith(".json")
        ):
            raise ValueError("generated_cases_filename must be a JSON filename without directories")
        self.ai_endpoint = self.ai_endpoint.strip()
        self.ai_model = self.ai_model.strip()
        self.ai_topic = self.ai_topic.strip()
        if self.case_source == "standalone_ai":
            if not self.ai_endpoint:
                raise ValueError("ai_endpoint is required when case_source is standalone_ai")
            if not self.ai_model:
                raise ValueError("ai_model is required when case_source is standalone_ai")
            if not self.ai_topic:
                raise ValueError("ai_topic is required when case_source is standalone_ai")
        return self


class TesciaDiagnosticArgsTD(TypedDict, total=False):
    data_in: str
    data_out: str
    files: str
    nfile: int
    minimum_evidence_confidence: float
    minimum_regression_coverage: float
    reset_target: bool
    case_source: str
    generated_cases_filename: str
    regenerate_cases: bool
    ai_provider: str
    ai_endpoint: str
    ai_model: str
    ai_topic: str
    ai_case_count: int
    ai_temperature: float
    ai_timeout_s: float


ArgsModel = TesciaDiagnosticArgs
ArgsOverrides = TesciaDiagnosticArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> TesciaDiagnosticArgs:
    return load_model_from_toml(TesciaDiagnosticArgs, settings_path, section=section)


def merge_args(
    base: TesciaDiagnosticArgs,
    overrides: TesciaDiagnosticArgsTD | None = None,
) -> TesciaDiagnosticArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: TesciaDiagnosticArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: TesciaDiagnosticArgs, **_: Any) -> TesciaDiagnosticArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "TesciaDiagnosticArgs",
    "TesciaDiagnosticArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
