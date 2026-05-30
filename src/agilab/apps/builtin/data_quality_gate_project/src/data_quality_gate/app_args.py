"""Argument helpers for the built-in data quality gate app."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path, PureWindowsPath
from typing import Any, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


def validate_relative_data_out(value: str | Path) -> Path:
    """Return a safe relative evidence path or raise ``ValueError``."""

    raw = str(value).strip()
    if not raw:
        raise ValueError("data_out must be a non-empty relative path")
    if raw.startswith("~"):
        raise ValueError("data_out must not use a home-directory shortcut")

    windows_path = PureWindowsPath(raw)
    if windows_path.is_absolute() or windows_path.drive:
        raise ValueError("data_out must be relative to the AGILAB share")

    candidate = Path(raw)
    if candidate.is_absolute():
        raise ValueError("data_out must be relative to the AGILAB share")
    if candidate == Path(".") or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("data_out must not be empty, '.', or contain parent traversal")
    return candidate


class DataQualityGateArgs(BaseModel):
    """Runtime parameters for the data quality gate app."""

    model_config = ConfigDict(extra="forbid")

    data_out: Path = Field(default_factory=lambda: Path("data_quality_gate/evidence"))
    baseline_rows: int = Field(default=240, ge=50, le=10000)
    candidate_rows: int = Field(default=220, ge=50, le=10000)
    drift_strength: float = Field(default=0.35, ge=0.0, le=1.0)
    seed: int = Field(default=2026, ge=0)
    include_quality_issues: bool = False
    reset_target: bool = False

    @field_validator("data_out", mode="before")
    @classmethod
    def _validate_data_out(cls, value: str | Path) -> Path:
        return validate_relative_data_out(value)


class DataQualityGateArgsTD(TypedDict, total=False):
    data_out: str
    baseline_rows: int
    candidate_rows: int
    drift_strength: float
    seed: int
    include_quality_issues: bool
    reset_target: bool


ArgsModel = DataQualityGateArgs
ArgsOverrides = DataQualityGateArgsTD


def filter_arg_overrides(overrides: Mapping[str, Any]) -> DataQualityGateArgsTD:
    """Keep only public data-quality args from a generic runtime kwargs mapping."""

    return cast(
        DataQualityGateArgsTD,
        {key: value for key, value in overrides.items() if key in DataQualityGateArgs.model_fields},
    )


def share_root_from_env(env: object) -> Path | None:
    """Resolve the active AGILAB share root when the runtime exposes it."""

    resolve_share_path = getattr(env, "resolve_share_path", None)
    if not callable(resolve_share_path):
        return None
    try:
        return Path(resolve_share_path(Path("."))).expanduser().resolve(strict=False)
    except (OSError, TypeError, ValueError):
        return None


def safe_reset_path(path: str | Path, *, share_root: str | Path | None, label: str = "path") -> Path:
    """Resolve and validate a path before destructive reset operations."""

    target = Path(path).expanduser().resolve(strict=False)
    if target == Path(target.anchor):
        raise ValueError(f"{label} reset target must not be the filesystem root")

    if share_root is None:
        if not target.is_absolute():
            raise ValueError(f"{label} reset target must be absolute when no share root is known")
        return target

    root = Path(share_root).expanduser().resolve(strict=False)
    if target == root:
        raise ValueError(f"{label} reset target must not be the share root")
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} reset target must stay under {root}") from exc
    return target


def load_args(settings_path: str | Path, *, section: str = "args") -> DataQualityGateArgs:
    return load_model_from_toml(DataQualityGateArgs, settings_path, section=section)


def merge_args(
    base: DataQualityGateArgs,
    overrides: DataQualityGateArgsTD | None = None,
) -> DataQualityGateArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: DataQualityGateArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: DataQualityGateArgs, **_: Any) -> DataQualityGateArgs:
    return DataQualityGateArgs(**args.model_dump(mode="json"))


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "DataQualityGateArgs",
    "DataQualityGateArgsTD",
    "dump_args",
    "ensure_defaults",
    "filter_arg_overrides",
    "load_args",
    "merge_args",
    "safe_reset_path",
    "share_root_from_env",
    "validate_relative_data_out",
]
