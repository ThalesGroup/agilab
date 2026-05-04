"""Argument helpers for the execution playground pandas app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class ExecutionPandasArgs(BaseModel):
    """Runtime parameters for the pandas execution playground."""

    model_config = ConfigDict(extra="forbid")

    data_in: Path = Field(default_factory=lambda: Path("execution_playground/dataset"))
    data_out: Path = Field(default_factory=lambda: Path("execution_pandas/results"))
    files: str = "*.csv"
    nfile: int = 16
    n_partitions: int = 16
    rows_per_file: int = 100_000
    n_groups: int = 32
    compute_passes: int = 32
    kernel_mode: Literal["dataframe", "typed_numeric"] = "typed_numeric"
    output_format: Literal["csv", "parquet"] = "csv"
    seed: int = 42
    reset_target: bool = False


class ExecutionPandasArgsTD(TypedDict, total=False):
    data_in: str
    data_out: str
    files: str
    nfile: int
    n_partitions: int
    rows_per_file: int
    n_groups: int
    compute_passes: int
    kernel_mode: str
    output_format: str
    seed: int
    reset_target: bool


ArgsModel = ExecutionPandasArgs
ArgsOverrides = ExecutionPandasArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> ExecutionPandasArgs:
    return load_model_from_toml(ExecutionPandasArgs, settings_path, section=section)


def merge_args(
    base: ExecutionPandasArgs,
    overrides: ExecutionPandasArgsTD | None = None,
) -> ExecutionPandasArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: ExecutionPandasArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: ExecutionPandasArgs, **_: Any) -> ExecutionPandasArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "ExecutionPandasArgs",
    "ExecutionPandasArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
