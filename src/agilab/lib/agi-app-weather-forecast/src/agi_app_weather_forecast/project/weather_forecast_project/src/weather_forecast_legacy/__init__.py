"""Compatibility API for the retired weather forecast legacy app project."""

from .app_args import (
    ArgsModel,
    ArgsOverrides,
    WeatherForecastLegacyArgs,
    WeatherForecastLegacyArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .reduction import WEATHER_FORECAST_LEGACY_REDUCE_CONTRACT
from .weather_forecast_legacy import WeatherForecastLegacy, WeatherForecastLegacyApp

__all__ = [
    "WEATHER_FORECAST_LEGACY_REDUCE_CONTRACT",
    "ArgsModel",
    "ArgsOverrides",
    "WeatherForecastLegacy",
    "WeatherForecastLegacyApp",
    "WeatherForecastLegacyArgs",
    "WeatherForecastLegacyArgsTD",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
