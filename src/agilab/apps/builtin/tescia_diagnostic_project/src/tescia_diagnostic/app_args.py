"""Argument helpers for the TeSciA diagnostic built-in app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


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

    @model_validator(mode="after")
    def _validate_file_glob(self) -> "TesciaDiagnosticArgs":
        self.files = self.files.strip() or "*.json"
        if not self.files.endswith(".json"):
            raise ValueError("files must select JSON diagnostic case files")
        return self


class TesciaDiagnosticArgsTD(TypedDict, total=False):
    data_in: str
    data_out: str
    files: str
    nfile: int
    minimum_evidence_confidence: float
    minimum_regression_coverage: float
    reset_target: bool


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
