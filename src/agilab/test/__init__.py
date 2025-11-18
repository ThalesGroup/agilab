"""Namespace package shim so app test modules share the ``test`` package."""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[misc]
