"""Namespace package shim so core test modules coexist with app tests."""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[misc]
