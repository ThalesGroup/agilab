"""Recover additive runtime symbols from an aligned source update."""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import threading
from collections import OrderedDict
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


class StaleRuntimeModuleError(RuntimeError):
    """Raised when a stale runtime module cannot be refreshed safely."""


_AGI_ENV_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
_LOAD_LOCK = threading.RLock()
_MODULE_CACHE_LIMIT = 16
_MODULE_CACHE: OrderedDict[tuple[Path, str], ModuleType] = OrderedDict()


def aligned_module_callable(module: ModuleType, attribute: str) -> Callable[..., Any]:
    """Return a callable from ``module`` or its current aligned source file.

    A long-lived Streamlit process can retain a module object loaded before an
    additive source update.  This helper does not reload or mutate that shared
    module.  It executes the current source under an isolated name, and only
    when the source remains inside the active ``agi_env`` package root.
    """

    candidate = getattr(module, attribute, None)
    if callable(candidate):
        return candidate

    origin = _aligned_module_origin(module)
    try:
        source = origin.read_bytes()
    except OSError as exc:
        raise StaleRuntimeModuleError(
            f"Cannot read the aligned source for stale module {module.__name__!r}."
        ) from exc
    refreshed = _load_aligned_module(origin, source)
    candidate = getattr(refreshed, attribute, None)
    if not callable(candidate):
        raise StaleRuntimeModuleError(
            f"The current aligned source for {module.__name__!r} does not expose "
            f"callable {attribute!r}."
        )
    return candidate


def _aligned_module_origin(module: ModuleType) -> Path:
    raw_origin = getattr(module, "__file__", None)
    if not isinstance(raw_origin, str) or not raw_origin:
        raise StaleRuntimeModuleError(
            f"Stale module {module.__name__!r} has no verifiable source file."
        )
    try:
        origin = Path(raw_origin).expanduser().resolve(strict=True)
        origin.relative_to(_AGI_ENV_PACKAGE_ROOT)
    except (OSError, ValueError) as exc:
        raise StaleRuntimeModuleError(
            f"Refusing to refresh stale module {module.__name__!r} outside the "
            f"active agi_env package root {_AGI_ENV_PACKAGE_ROOT}."
        ) from exc
    if not origin.is_file():
        raise StaleRuntimeModuleError(
            f"Aligned source for stale module {module.__name__!r} is not a file: {origin}."
        )
    return origin


def _load_aligned_module(
    origin: Path,
    source: bytes,
) -> ModuleType:
    source_digest = hashlib.sha256(source).hexdigest()
    cache_key = (origin, source_digest)
    identity_digest = hashlib.sha256(
        f"{origin}\0{source_digest}".encode("utf-8")
    ).hexdigest()[:24]
    synthetic_name = f"agi_env.runtime._hot_source_{identity_digest}"
    with _LOAD_LOCK:
        cached = _MODULE_CACHE.get(cache_key)
        if cached is not None:
            _MODULE_CACHE.move_to_end(cache_key)
            return cached
        spec = importlib.util.spec_from_file_location(synthetic_name, origin)
        if spec is None or spec.loader is None:
            raise StaleRuntimeModuleError(
                f"Unable to load aligned runtime source at {origin}."
            )
        refreshed = importlib.util.module_from_spec(spec)
        sys.modules[synthetic_name] = refreshed
        try:
            exec(compile(source, str(origin), "exec"), refreshed.__dict__)
        # Boundary: convert arbitrary aligned module execution failures into
        # the stable stale-runtime contract after removing partial state.
        except Exception as exc:
            if sys.modules.get(synthetic_name) is refreshed:
                sys.modules.pop(synthetic_name, None)
            raise StaleRuntimeModuleError(
                f"Unable to execute aligned runtime source at {origin}."
            ) from exc
        _MODULE_CACHE[cache_key] = refreshed
        while len(_MODULE_CACHE) > _MODULE_CACHE_LIMIT:
            _old_key, old_module = _MODULE_CACHE.popitem(last=False)
            if sys.modules.get(old_module.__name__) is old_module:
                sys.modules.pop(old_module.__name__, None)
        return refreshed


def _clear_aligned_module_cache() -> None:
    """Clear isolated hot-source modules; used by focused regression tests."""

    with _LOAD_LOCK:
        for module in _MODULE_CACHE.values():
            if sys.modules.get(module.__name__) is module:
                sys.modules.pop(module.__name__, None)
        _MODULE_CACHE.clear()
