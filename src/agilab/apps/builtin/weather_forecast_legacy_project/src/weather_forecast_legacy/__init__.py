"""Weather forecasting builtin app migrated from the notebook pilot."""

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
from .weather_forecast_legacy import WeatherForecastLegacy, WeatherForecastLegacyApp
from .reduction import WEATHER_FORECAST_LEGACY_REDUCE_CONTRACT

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "WEATHER_FORECAST_LEGACY_REDUCE_CONTRACT",
    "WeatherForecastLegacyArgs",
    "WeatherForecastLegacyArgsTD",
    "WeatherForecastLegacy",
    "WeatherForecastLegacyApp",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
