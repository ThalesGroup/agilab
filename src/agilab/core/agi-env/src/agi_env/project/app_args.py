"""Utilities for loading and persisting app argument models."""

from __future__ import annotations

from io import BufferedWriter
from pathlib import Path
from typing import Any, Callable, Mapping, Type, TypeVar

import tomllib

from pydantic import BaseModel, ValidationError

from agi_env.app_settings_support import prepare_app_settings_for_write

TModel = TypeVar("TModel", bound=BaseModel)

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)


def _is_missing_module(exc: ModuleNotFoundError, module_name: str) -> bool:
    return getattr(exc, "name", None) == module_name

def model_to_payload(model: BaseModel) -> dict[str, Any]:
    """Return a JSON/TOML friendly representation of the model."""

    return model.model_dump(mode="json")


def prefer_persisted_value(persisted_value: Any, fallback_value: Any) -> Any:
    """Keep an explicit stored value; use ``fallback_value`` only when it is absent."""

    if persisted_value is None or persisted_value is False:
        return fallback_value
    if isinstance(persisted_value, str) and persisted_value == "":
        return fallback_value
    return persisted_value


def merge_model_data(model: BaseModel, overrides: Mapping[str, Any] | None = None) -> BaseModel:
    """Return a copy of ``model`` with ``overrides`` applied."""

    data = model.model_dump()
    if overrides:
        data.update(dict(overrides))
    return model.__class__(**data)


def load_model_from_toml(
    model_cls: Type[TModel],
    settings_path: str | Path,
    *,
    section: str = "args",
) -> TModel:
    """Load a Pydantic model from a TOML section."""

    settings_path = Path(settings_path)
    payload: dict[str, Any] = {}
    if settings_path.exists():
        with settings_path.open("rb") as handle:
            doc = tomllib.load(handle)
        if section in doc:
            payload = dict(doc[section])

    try:
        return model_cls(**payload)
    except ValidationError as exc:
        raise ValueError(
            f"Invalid {model_cls.__name__} stored in {settings_path} [{section}]: {exc}"
        ) from exc


def dump_model_to_toml(
    model: BaseModel,
    settings_path: str | Path,
    *,
    section: str = "args",
    create_missing: bool = True,
) -> None:
    """Persist a Pydantic model into a TOML section."""

    settings_path = Path(settings_path)
    doc: dict[str, Any] = {}
    if settings_path.exists():
        with settings_path.open("rb") as handle:
            doc = tomllib.load(handle)
    elif not create_missing:
        raise FileNotFoundError(f"Settings file not found: {settings_path}")

    doc[section] = model_to_payload(model)
    doc = prepare_app_settings_for_write(doc)

    dumper: Callable[[dict[str, Any], BufferedWriter], None] | None = None
    try:
        import tomli_w  # type: ignore[import-not-found]

        def _dump_with_tomli_w(data: dict[str, Any], stream: BufferedWriter) -> None:
            tomli_w.dump(data, stream)

        dumper = _dump_with_tomli_w
    except ModuleNotFoundError as exc:
        if not _is_missing_module(exc, "tomli_w"):
            raise
        try:
            from tomlkit import dumps as tomlkit_dumps
        except ModuleNotFoundError as exc:
            if not _is_missing_module(exc, "tomlkit"):
                raise
            raise RuntimeError(
                "Writing settings requires either 'tomli-w' or 'tomlkit'."
            ) from exc

        def _dump_with_tomlkit(data: dict[str, Any], stream: BufferedWriter) -> None:
            stream.write(tomlkit_dumps(data).encode("utf-8"))

        dumper = _dump_with_tomlkit

    logger.info(f"mkdir {settings_path.parent}")
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("wb") as handle:
        dumper(doc, handle)
