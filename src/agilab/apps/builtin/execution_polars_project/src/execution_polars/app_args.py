"""Argument helpers for the execution playground polars app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class ExecutionPolarsArgs(BaseModel):
    """Runtime parameters for the polars execution playground."""

    model_config = ConfigDict(extra="forbid")

    data_in: Path = Field(default_factory=lambda: Path("execution_playground/dataset"))
    data_out: Path = Field(default_factory=lambda: Path("execution_polars/results"))
    files: str = "*.csv"
    nfile: int = 16
    n_partitions: int = 16
    rows_per_file: int = 100_000
    n_groups: int = 32
    compute_passes: int = 32
    output_format: Literal["csv", "parquet"] = "csv"
    seed: int = 42
    reset_target: bool = False


class ExecutionPolarsArgsTD(TypedDict, total=False):
    data_in: str
    data_out: str
    files: str
    nfile: int
    n_partitions: int
    rows_per_file: int
    n_groups: int
    compute_passes: int
    output_format: str
    seed: int
    reset_target: bool


ArgsModel = ExecutionPolarsArgs
ArgsOverrides = ExecutionPolarsArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> ExecutionPolarsArgs:
    return load_model_from_toml(ExecutionPolarsArgs, settings_path, section=section)


def merge_args(
    base: ExecutionPolarsArgs,
    overrides: ExecutionPolarsArgsTD | None = None,
) -> ExecutionPolarsArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: ExecutionPolarsArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: ExecutionPolarsArgs, **_: Any) -> ExecutionPolarsArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "ExecutionPolarsArgs",
    "ExecutionPolarsArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
