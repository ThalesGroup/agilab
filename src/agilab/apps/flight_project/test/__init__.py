"""Namespace package shim so app tests avoid name collisions."""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[misc]
