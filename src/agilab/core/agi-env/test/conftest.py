"""Test-only UI shims for agi-env's optional Streamlit helpers."""

from __future__ import annotations

import importlib.util
import sys
import types
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar


_F = TypeVar("_F", bound=Callable[..., Any])


class _SessionState(dict[str, Any]):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


class _NoopContainer:
    def __getattr__(self, _name: str) -> Callable[..., None]:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


class _StreamlitStub(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("streamlit")
        self.session_state = _SessionState()
        self.sidebar = _NoopContainer()
        self.query_params: dict[str, Any] = {}

    def cache_data(self, func: _F | None = None, **_kwargs: Any) -> _F | Callable[[_F], _F]:
        def _decorate(inner: _F) -> _F:
            return inner

        if func is None:
            return _decorate
        return _decorate(func)

    def checkbox(self, _label: str, value: bool = False, **_kwargs: Any) -> bool:
        return value

    def number_input(self, _label: str, **kwargs: Any) -> Any:
        return kwargs.get("value")

    def text_area(self, _label: str, value: str = "", **_kwargs: Any) -> str:
        return value

    def text_input(self, _label: str, value: str = "", **_kwargs: Any) -> str:
        return value

    def selectbox(self, _label: str, options: list[Any], index: int = 0, **_kwargs: Any) -> Any:
        return options[index]

    def date_input(self, _label: str, value: date, **_kwargs: Any) -> date:
        return value

    def __getattr__(self, _name: str) -> Callable[..., None]:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


if "streamlit" not in sys.modules and importlib.util.find_spec("streamlit") is None:
    sys.modules["streamlit"] = _StreamlitStub()
