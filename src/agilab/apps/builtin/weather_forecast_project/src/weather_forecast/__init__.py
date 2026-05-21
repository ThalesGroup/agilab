"""Weather forecasting builtin app migrated from the notebook pilot."""

from .app_args import (
    ArgsModel,
    ArgsOverrides,
    WeatherForecastArgs,
    WeatherForecastArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .weather_forecast import WeatherForecast, WeatherForecastApp
from .reduction import WEATHER_FORECAST_REDUCE_CONTRACT

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "WEATHER_FORECAST_REDUCE_CONTRACT",
    "WeatherForecastArgs",
    "WeatherForecastArgsTD",
    "WeatherForecast",
    "WeatherForecastApp",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
