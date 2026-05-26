"""Argument helpers for the built-in R stage smoke app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class RStageSmokeArgs(BaseModel):
    """Runtime parameters for the Rscript JSON/artifact smoke stage."""

    model_config = ConfigDict(extra="forbid")

    data_out: Path = Field(default_factory=lambda: Path("r_stage_smoke/evidence"))
    script_path: Path = Field(default_factory=lambda: Path("scripts/summarize.R"))
    rscript: str = "Rscript"
    x: list[float] = Field(default_factory=lambda: [1.0, 2.0, 3.0, 4.0, 5.0], min_length=1)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)
    reset_target: bool = False

    @field_validator("rscript")
    @classmethod
    def _rscript_not_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("rscript command must not be blank")
        return normalized


class RStageSmokeArgsTD(TypedDict, total=False):
    data_out: str
    script_path: str
    rscript: str
    x: list[float]
    timeout_seconds: int
    reset_target: bool


ArgsModel = RStageSmokeArgs
ArgsOverrides = RStageSmokeArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> RStageSmokeArgs:
    return load_model_from_toml(RStageSmokeArgs, settings_path, section=section)


def merge_args(
    base: RStageSmokeArgs,
    overrides: RStageSmokeArgsTD | None = None,
) -> RStageSmokeArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: RStageSmokeArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: RStageSmokeArgs, **_: Any) -> RStageSmokeArgs:
    return RStageSmokeArgs(**args.model_dump(mode="json"))


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "RStageSmokeArgs",
    "RStageSmokeArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
