"""Argument helpers for the weather forecast legacy builtin app."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data


class WeatherForecastLegacyArgs(BaseModel):
    """Runtime parameters for the notebook-to-AGILAB forecast example."""

    model_config = ConfigDict(extra="forbid")

    data_in: Path = Field(default_factory=lambda: Path("weather_forecast_legacy/dataset"))
    data_out: Path = Field(default_factory=lambda: Path("weather_forecast_legacy/results"))
    files: str = "*.csv"
    nfile: int = Field(default=1, ge=1, le=50)
    station: str = "Paris-Montsouris"
    target_column: Literal["tmin_c", "tmax_c", "tmoy_c"] = "tmax_c"
    lags: int = Field(default=7, ge=1, le=30)
    horizon_days: int = Field(default=7, ge=1, le=30)
    validation_days: int = Field(default=9, ge=7, le=120)
    n_estimators: int = Field(default=100, ge=10, le=500)
    random_state: int = Field(default=42, ge=0)
    reset_target: bool = False

    @model_validator(mode="after")
    def _validate_consistency(self) -> "WeatherForecastLegacyArgs":
        self.station = self.station.strip()
        if not self.station:
            raise ValueError("station must not be empty")
        if self.validation_days <= self.horizon_days:
            raise ValueError("validation_days must be greater than horizon_days")
        return self


class WeatherForecastLegacyArgsTD(TypedDict, total=False):
    data_in: str
    data_out: str
    files: str
    nfile: int
    station: str
    target_column: str
    lags: int
    horizon_days: int
    validation_days: int
    n_estimators: int
    random_state: int
    reset_target: bool


ArgsModel = WeatherForecastLegacyArgs
ArgsOverrides = WeatherForecastLegacyArgsTD


def load_args(settings_path: str | Path, *, section: str = "args") -> WeatherForecastLegacyArgs:
    return load_model_from_toml(WeatherForecastLegacyArgs, settings_path, section=section)


def merge_args(
    base: WeatherForecastLegacyArgs,
    overrides: WeatherForecastLegacyArgsTD | None = None,
) -> WeatherForecastLegacyArgs:
    return merge_model_data(base, overrides)


def dump_args(
    args: WeatherForecastLegacyArgs,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    dump_model_to_toml(args, settings_path, section=section, create_missing=create_missing)


def ensure_defaults(args: WeatherForecastLegacyArgs, **_: Any) -> WeatherForecastLegacyArgs:
    return args


__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "WeatherForecastLegacyArgs",
    "WeatherForecastLegacyArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
