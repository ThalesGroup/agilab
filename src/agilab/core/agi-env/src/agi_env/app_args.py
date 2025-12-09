"""Utilities for loading and persisting app argument models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, MutableMapping, Type, TypeVar

import tomllib

from pydantic import BaseModel, ValidationError

TModel = TypeVar("TModel", bound=BaseModel)

from agi_env.agi_logger import AgiLogger

logger = AgiLogger.get_logger(__name__)

def model_to_payload(model: BaseModel) -> dict[str, Any]:
    """Return a JSON/TOML friendly representation of the model."""

    return model.model_dump(mode="json")


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

    dumper: Callable[[dict[str, Any], BinaryIO], None] | None = None
    try:
        import tomli_w  # type: ignore[import-not-found]

        def _dump_with_tomli_w(data: dict[str, Any], stream: BinaryIO) -> None:
            tomli_w.dump(data, stream)

        dumper = _dump_with_tomli_w
    except ModuleNotFoundError:
        try:
            from tomlkit import dumps as tomlkit_dumps
        except Exception as exc:  # pragma: no cover - defensive guard
            raise RuntimeError(
                "Writing settings requires either 'tomli-w' or 'tomlkit'."
            ) from exc

        def _dump_with_tomlkit(data: dict[str, Any], stream: BinaryIO) -> None:
            stream.write(tomlkit_dumps(data).encode("utf-8"))

        dumper = _dump_with_tomlkit
    except Exception as exc:  # pragma: no cover - defensive guard
        raise RuntimeError("Writing settings requires the 'tomli-w' package") from exc

    logger.info(f"mkdir {settings_path.parent}")
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    with settings_path.open("wb") as handle:
        dumper(doc, handle)
