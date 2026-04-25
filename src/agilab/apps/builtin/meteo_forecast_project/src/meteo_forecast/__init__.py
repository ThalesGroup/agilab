"""Weather forecasting builtin app migrated from the notebook pilot."""

from .app_args import (
    ArgsModel,
    ArgsOverrides,
    MeteoForecastArgs,
    MeteoForecastArgsTD,
    dump_args,
    ensure_defaults,
    load_args,
    merge_args,
)
from .meteo_forecast import MeteoForecast, MeteoForecastApp
from .reduction import METEO_FORECAST_REDUCE_CONTRACT

__all__ = [
    "ArgsModel",
    "ArgsOverrides",
    "METEO_FORECAST_REDUCE_CONTRACT",
    "MeteoForecastArgs",
    "MeteoForecastArgsTD",
    "MeteoForecast",
    "MeteoForecastApp",
    "dump_args",
    "ensure_defaults",
    "load_args",
    "merge_args",
]
