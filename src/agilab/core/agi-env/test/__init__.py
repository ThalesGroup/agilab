"""Namespace package shim so AgiEnv tests share the global ``test`` package."""

from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[misc]
