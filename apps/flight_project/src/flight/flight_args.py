"""Shared validation and persistence helpers for Flight project arguments."""

from __future__ import annotations

import re
import socket
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypedDict

import tomli

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agi_env.app_args import (
    dump_model_to_toml,
    load_model_from_toml,
    merge_model_data,
    model_to_payload,
)


ARGS_SECTION = "args"
_DATEMIN_LOWER_BOUND = date(2020, 1, 1)
_DATEMAX_UPPER_BOUND = date(2021, 6, 1)


class FlightArgs(BaseModel):
    """Validated configuration for the Flight worker."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    data_source: Literal["file", "hawk"] = "file"
    data_uri: Path = Field(default_factory=lambda: Path("data/flight/dataset"))
    files: str = "*"
    nfile: int = Field(default=1, ge=0)
    nskip: int = Field(default=0, ge=0)
    nread: int = Field(default=0, ge=0)
    sampling_rate: float = Field(default=1.0, ge=0)
    datemin: date = Field(default_factory=lambda: _DATEMIN_LOWER_BOUND)
    datemax: date = Field(default_factory=lambda: date(2021, 1, 1))
    output_format: Literal["parquet", "csv"] = "parquet"

    @field_validator("data_uri", mode="before")
    @classmethod
    def _coerce_data_uri(cls, value: Any) -> Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str):
            return Path(value)
        raise TypeError("data_uri must be a string or Path value")

    @field_validator("datemin")
    @classmethod
    def _check_datemin(cls, value: date) -> date:
        if value < _DATEMIN_LOWER_BOUND:
            raise ValueError(f"datemin must be on or after {_DATEMIN_LOWER_BOUND.isoformat()}")
        return value

    @field_validator("datemax")
    @classmethod
    def _check_datemax(cls, value: date, info: Any) -> date:
        datemin = info.data.get("datemin") if hasattr(info, "data") else None
        if datemin and value < datemin:
            raise ValueError("datemax must be on or after datemin")
        if value > _DATEMAX_UPPER_BOUND:
            raise ValueError(f"datemax must be on or before {_DATEMAX_UPPER_BOUND.isoformat()}")
        return value

    @field_validator("files")
    @classmethod
    def _check_regex(cls, value: str) -> str:
        candidate = value
        if candidate.startswith("*"):
            candidate = "." + candidate
        try:
            re.compile(candidate)
        except re.error as exc:
            raise ValueError(f"The provided string '{value}' is not a valid regex.") from exc
        return value

    def to_toml_payload(self) -> dict[str, Any]:
        """Return a TOML-friendly representation (Path/date → str)."""

        return model_to_payload(self)


class FlightArgsTD(TypedDict, total=False):
    data_source: str
    data_uri: str
    files: str
    nfile: int
    nskip: int
    nread: int
    sampling_rate: float
    datemin: str
    datemax: str
    output_format: str


def load_args_from_toml(
    settings_path: str | Path,
    section: str = ARGS_SECTION,
) -> FlightArgs:
    """Load arguments from a TOML file, applying model defaults when missing."""

    return load_model_from_toml(FlightArgs, settings_path, section=section)


def merge_args(base: FlightArgs, overrides: FlightArgsTD | None = None) -> FlightArgs:
    """Return a new instance with overrides applied on top of ``base``."""

    return merge_model_data(base, overrides)


def apply_source_defaults(
    args: FlightArgs,
    *,
    host_ip: str | None = None,
) -> FlightArgs:
    """Ensure source-specific defaults for missing values."""

    overrides: FlightArgsTD = {}
    if args.data_source == "file":
        if not str(args.data_uri).strip():
            overrides["data_uri"] = "data/flight/dataset"
        if not args.files:
            overrides["files"] = "*"
    else:
        if host_ip:
            host = host_ip
        else:
            try:
                host = socket.gethostbyname(socket.gethostname())
            except OSError:
                host = "127.0.0.1"
        default_uri = f"https://admin:admin@{host}:9200/"
        current_uri = str(args.data_uri)
        if not current_uri.strip() or current_uri == "data/flight/dataset":
            overrides["data_uri"] = default_uri
        if not args.files or args.files == "*":
            overrides["files"] = "hawk.user-admin.1"

    return merge_args(args, overrides) if overrides else args


def dump_args_to_toml(
    args: FlightArgs,
    settings_path: str | Path,
    section: str = ARGS_SECTION,
    create_missing: bool = True,
) -> None:
    """Persist arguments back to the TOML file (overwriting only the section)."""

    settings_path = Path(settings_path)
    doc: dict[str, Any] = {}
    if settings_path.exists():
        with settings_path.open("rb") as handle:
            doc = tomli.load(handle)
    elif not create_missing:
        raise FileNotFoundError(f"Settings file not found: {settings_path}")

    dump_model_to_toml(
        args,
        settings_path=settings_path,
        section=section,
        create_missing=create_missing,
    )


ArgsModel = FlightArgs
ArgsOverrides = FlightArgsTD


def load_args(
    settings_path: str | Path,
    *,
    section: str = ARGS_SECTION,
) -> FlightArgs:
    return load_args_from_toml(settings_path, section=section)


def dump_args(
    args: FlightArgs,
    settings_path: str | Path,
    *,
    section: str = ARGS_SECTION,
    create_missing: bool = True,
) -> None:
    dump_args_to_toml(
        args,
        settings_path,
        section=section,
        create_missing=create_missing,
    )


def ensure_defaults(args: FlightArgs, **kwargs: Any) -> FlightArgs:
    return apply_source_defaults(args, **kwargs)


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "FlightArgs",
    "FlightArgsTD",
    "apply_source_defaults",
    "dump_args",
    "dump_args_to_toml",
    "ensure_defaults",
    "load_args",
    "load_args_from_toml",
    "merge_args",
]
