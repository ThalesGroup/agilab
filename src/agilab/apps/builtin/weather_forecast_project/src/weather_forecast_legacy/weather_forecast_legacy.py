"""Historical manager names backed by the current weather forecast manager."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from weather_forecast.weather_forecast import WeatherForecast

from .app_args import (
    ArgsOverrides,
    WeatherForecastLegacyArgs,
    ensure_defaults,
    load_args,
    merge_args,
)


class WeatherForecastLegacy(WeatherForecast):
    """Compatibility manager retaining legacy defaults and public class names."""

    def __init__(
        self,
        env,
        args: WeatherForecastLegacyArgs | None = None,
        **kwargs: ArgsOverrides,
    ) -> None:
        verbose = int(kwargs.pop("verbose", getattr(env, "verbose", 0) or 0))
        if args is None:
            try:
                args = WeatherForecastLegacyArgs(**kwargs)
            except ValidationError as exc:
                raise ValueError(
                    f"Invalid WeatherForecastLegacy arguments: {exc}"
                ) from exc
        super().__init__(env, args=args, verbose=verbose)

    @classmethod
    def from_toml(
        cls,
        env,
        settings_path: str | Path = "app_settings.toml",
        section: str = "args",
        **overrides: ArgsOverrides,
    ) -> WeatherForecastLegacy:
        base = load_args(settings_path, section=section)
        merged = ensure_defaults(merge_args(base, overrides or None), env=env)
        return cls(env, args=merged)


class WeatherForecastLegacyApp(WeatherForecastLegacy):
    """Compatibility alias retaining the historical ``App`` suffix."""


__all__ = ["WeatherForecastLegacy", "WeatherForecastLegacyApp"]
