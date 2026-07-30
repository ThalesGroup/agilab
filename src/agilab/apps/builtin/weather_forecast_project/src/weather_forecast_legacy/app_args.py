"""Historical argument API backed by the current weather forecast implementation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agi_env.app_args import dump_model_to_toml, load_model_from_toml, merge_model_data
from pydantic import Field
from weather_forecast.app_args import WeatherForecastArgs, WeatherForecastArgsTD


class WeatherForecastLegacyArgs(WeatherForecastArgs):
    """Compatibility model retaining the historical default data namespace."""

    data_in: Path = Field(
        default_factory=lambda: Path("weather_forecast_legacy/dataset")
    )
    data_out: Path = Field(
        default_factory=lambda: Path("weather_forecast_legacy/results")
    )


class WeatherForecastLegacyArgsTD(WeatherForecastArgsTD, total=False):
    """Typed compatibility overrides for the historical manager name."""


ArgsModel = WeatherForecastLegacyArgs
ArgsOverrides = WeatherForecastLegacyArgsTD


def load_args(
    settings_path: str | Path,
    *,
    section: str = "args",
) -> WeatherForecastLegacyArgs:
    return load_model_from_toml(
        WeatherForecastLegacyArgs,
        settings_path,
        section=section,
    )


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
    dump_model_to_toml(
        args,
        settings_path,
        section=section,
        create_missing=create_missing,
    )


def ensure_defaults(
    args: WeatherForecastLegacyArgs,
    **_: Any,
) -> WeatherForecastLegacyArgs:
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
