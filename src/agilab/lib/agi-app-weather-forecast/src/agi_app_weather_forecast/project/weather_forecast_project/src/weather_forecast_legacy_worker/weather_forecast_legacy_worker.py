"""Historical worker name backed by the current weather forecast worker."""

from weather_forecast_legacy.reduction import write_reduce_artifact
from weather_forecast_worker.weather_forecast_worker import WeatherForecastWorker


class WeatherForecastLegacyWorker(WeatherForecastWorker):
    """Compatibility worker retaining the historical reducer identity."""

    reduce_artifact_writer = staticmethod(write_reduce_artifact)


__all__ = ["WeatherForecastLegacyWorker"]
