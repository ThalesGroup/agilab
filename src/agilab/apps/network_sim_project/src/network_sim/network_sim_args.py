"""Argument definitions for the Network Simulation app."""

from __future__ import annotations

import re
import socket
from datetime import date
from pathlib import Path
from typing import Any, Literal, TypedDict

import tomli

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator, PositiveInt

from agi_env.app_args import (
    dump_model_to_toml,
    load_model_from_toml,
    merge_model_data,
    model_to_payload,
)

ARGS_SECTION = "args"

class NetworkSimArgs(BaseModel):

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    @model_validator(mode="before")
    @classmethod
    def _migrate_legacy_keys(cls, data: Any):
        if isinstance(data, dict) and "data_uri" in data and "data_in" not in data:
            data = dict(data)
            data["data_in"] = data.pop("data_uri")
        return data

    data_source: str
    data_in: Path = Field(default_factory=lambda: Path("data/network_sim/dataset"))
    net_size: PositiveInt = Field(
        default=12,
        ge=4,
        description="Number of nodes in the generated topology",
    )
    seed: int = Field(default=42, description="Random seed for reproducibility")
    topology_filename: str = Field(
        default="topology.gml",
        description="Filename used to store the generated GML topology",
    )
    summary_filename: str = Field(
        default="topology_summary.json",
        description="Filename used to store the topology summary JSON",
    )
    data_in: Path = Field(
        default_factory=lambda: Path("~/data/network_sim"),
        description="Directory where generated artefacts are written",
    )

    @field_validator("data_in", mode="before")
    @classmethod
    def _coerce_data_in(cls, value: Any) -> Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str):
            return Path(value)
        raise TypeError("data_in must be a string or Path value")

    def to_toml_payload(self) -> dict[str, Any]:
        """Return a TOML-friendly representation (Path/date → str)."""

        return model_to_payload(self)


class NetworkSimArgsTD(TypedDict, total=False):
    data_source: str
    data_in: str
    net_size: int
    seed: int
    topology_filename: str
    summary_filename: str


def load_args_from_toml(
    settings_path: str | Path,
    section: str = ARGS_SECTION,
) -> NetworkSimArgs:
    """Load arguments from a TOML file, applying model defaults when missing."""

    return load_model_from_toml(NetworkSimArgs, settings_path, section=section)


def merge_args(base: NetworkSimArgs, overrides: NetworkSimArgsTD | None = None) -> NetworkSimArgs:
    """Return a new instance with overrides applied on top of ``base``."""

    return merge_model_data(base, overrides)

def apply_source_defaults(
    args: NetworkSimArgs,
    *,
    host_ip: str | None = None,
    env: Any | None = None,
) -> NetworkSimArgs:
    """Ensure source-specific defaults for missing values."""

    overrides: NetworkSimArgsTD = {}
    if args.data_source == "file":
        if not str(args.data_in).strip():
            default_path = Path("data/network_sim/dataset")
            if env is not None:
                try:
                    base = Path(getattr(env, "home_abs", Path.home()))
                    default_path = (base / default_path).expanduser()
                except Exception:
                    default_path = default_path.expanduser()
            else:
                default_path = default_path.expanduser()
            overrides["data_in"] = str(default_path)
    else:
        if host_ip:
            host = host_ip
        else:
            try:
                host = socket.gethostbyname(socket.gethostname())
            except OSError:
                host = "127.0.0.1"
        default_uri = f"https://admin:admin@{host}:9200/"
        current_uri = str(args.data_in)
        if not current_uri.strip() or current_uri == "data/network_sim/dataset":
            overrides["data_in"] = default_uri

    return merge_args(args, overrides) if overrides else args

def dump_args_to_toml(
    args: NetworkSimArgs,
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


ArgsModel = NetworkSimArgs
ArgsOverrides = NetworkSimArgsTD


def load_args(
    settings_path: str | Path,
    *,
    section: str = ARGS_SECTION,
) -> NetworkSimArgs:
    return load_args_from_toml(settings_path, section=section)


def dump_args(
    args: NetworkSimArgs,
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


def ensure_defaults(args: NetworkSimArgs, **kwargs: Any) -> NetworkSimArgs:
    return apply_source_defaults(args, **kwargs)


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "NetworkSimArgs",
    "NetworkSimArgsTD",
    "apply_source_defaults",
    "dump_args",
    "dump_args_to_toml",
    "ensure_defaults",
    "load_args",
    "load_args_from_toml",
    "merge_args",
]
